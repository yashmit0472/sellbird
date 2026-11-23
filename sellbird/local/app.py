"""Local dashboard and FastAPI endpoints. Launch with python -m sellbird.local."""

import asyncio
import json
import os
import shutil
import subprocess
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Annotated

import httpx
import psutil
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints

from sellbird.dashboard_auth import DashboardGuard, TokenStore
from sellbird.pidfile import hold_loop_lock, release_loop_lock

from .engine import ENDPOINT, MODELS, STEPS, Retriever, Workflow
from .store import Store

HERE = Path(__file__).parent
DATA = Path(os.environ.get("SELLBIRD_LOCAL_DATA", "data/local")).resolve()
Name = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]


class Product(BaseModel):
    company: Name
    name: Name
    brief: Annotated[str, StringConstraints(strip_whitespace=True, min_length=20, max_length=2800)]
    exclusion_phrases: Annotated[str, StringConstraints(strip_whitespace=True, max_length=1000)] = ""


class SavedPage(BaseModel):
    name: Name
    source: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=1200)]


class ManualPage(SavedPage):
    body: Annotated[str, StringConstraints(strip_whitespace=True, min_length=30, max_length=12000)]


class Snapshot(SavedPage):
    html: str = Field(min_length=30, max_length=500000)


class PublicPage(BaseModel):
    name: Name
    url: str = Field(min_length=8, max_length=1200)
    permitted: bool


class Run(BaseModel):
    product_id: int
    prospect_id: int | None = None
    model: str
    reply: str = Field("", max_length=4000)


def hardware():
    ram = round(psutil.virtual_memory().total / 2**30, 1)
    available = round(psutil.virtual_memory().available / 2**30, 1)
    gpu_name, vram = "No NVIDIA GPU detected (CPU can be used)", 0
    nvidia = shutil.which("nvidia-smi")
    if nvidia:
        try:
            values = subprocess.check_output(
                [nvidia, "--query-gpu=name,memory.total", "--format=csv,noheader,nounits"],
                text=True, timeout=3, stderr=subprocess.DEVNULL,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            cards = [line.rsplit(",", 1) for line in values.splitlines() if "," in line]
            gpu_name, memory = max(cards, key=lambda card: int(card[1]))
            vram = round(int(memory) / 1024, 1)
        except (OSError, ValueError, subprocess.SubprocessError):
            pass
    standard = "qwen3:4b" if available >= 7 or vram >= 6 else MODELS[0]
    high = "qwen3:14b" if vram >= 14 and ram >= 24 else "qwen3:8b"
    return {"ram_gib": ram, "available_gib": available,
            "cpu": os.environ.get("PROCESSOR_IDENTIFIER", "CPU"),
            "logical_cpus": psutil.cpu_count(), "gpu": gpu_name.strip(), "vram_gib": vram,
            "standard": standard, "high_performance": high,
            "recommended": high if vram >= 8 and ram >= 15 else standard}


def create_app(data_dir=DATA):
    store = Store(data_dir / "workspace.db")
    tokens = TokenStore(data_dir / "dashboard-token")
    inference_verified = os.environ.get("SELLBIRD_LOCAL_OLLAMA_UNVERIFIED") != "1"
    workflow = Workflow(store, Retriever(data_dir / "models" / "all-MiniLM-L6-v2"), inference_verified)
    offline = os.environ.get("SELLBIRD_LOCAL_OFFLINE") == "1"

    @asynccontextmanager
    async def lifespan(_app):
        store.initialize()
        lock = hold_loop_lock(data_dir / "worker.lock")
        if lock is None:
            raise RuntimeError("This workspace is already open or its worker lock cannot be created.")
        try:
            store.write("UPDATE jobs SET status = 'queued' WHERE status = 'running'")
            worker = asyncio.create_task(workflow.work())
            try:
                yield
            finally:
                worker.cancel()
                with suppress(asyncio.CancelledError):
                    await worker
        finally:
            release_loop_lock(lock)

    app = FastAPI(title="Sellbird Local", lifespan=lifespan, docs_url=None, redoc_url=None)
    app.add_middleware(DashboardGuard, store=tokens)
    app.mount("/static", StaticFiles(directory=HERE / "web"), name="static")

    @app.get("/")
    def home():
        return FileResponse(HERE / "web" / "index.html")

    @app.get("/api/status")
    async def status():
        ready, installed = False, []
        if inference_verified:
            try:
                async with httpx.AsyncClient(trust_env=False, timeout=2, follow_redirects=False) as client:
                    response = await client.get(f"{ENDPOINT}/api/tags")
                    response.raise_for_status()
                    installed = [item["name"] for item in response.json()["models"] if item["name"] in MODELS]
                    ready = True
            except (httpx.HTTPError, ValueError, KeyError, TypeError):
                pass
        return {"endpoint": ENDPOINT, "ollama": ready, "installed": installed,
                "models": MODELS, "offline": offline, "hardware": await asyncio.to_thread(hardware),
                "embeddings": workflow.retriever.directory.is_dir()}

    @app.get("/api/workspace")
    def workspace():
        return {
            "products": store.rows("SELECT * FROM products ORDER BY company, name"),
            "prospects": store.rows(
                """SELECT p.*, COUNT(e.id) AS sources FROM prospects p LEFT JOIN evidence e
                   ON e.prospect_id = p.id GROUP BY p.id ORDER BY p.name"""
            ),
            "jobs": store.rows(
                """SELECT j.id, j.status, j.model, j.error, j.created_at, j.product_id, j.prospect_id,
                          p.name AS product, q.name AS prospect,
                          json_extract(j.results, '$.score.total') AS score
                   FROM jobs j JOIN products p ON p.id = j.product_id
                   LEFT JOIN prospects q ON q.id = j.prospect_id ORDER BY j.id DESC LIMIT 200"""
            ),
        }

    def save_product(item):
        store.write(
            """INSERT INTO products(company, name, brief, exclusion_phrases) VALUES (?, ?, ?, ?)
               ON CONFLICT(company, name) DO UPDATE SET
               brief = excluded.brief, exclusion_phrases = excluded.exclusion_phrases""",
            (item.company, item.name, item.brief, item.exclusion_phrases),
        )

    @app.post("/api/products")
    def product(item: Product):
        save_product(item)
        return {"saved": True}

    @app.post("/api/evidence")
    def evidence(item: ManualPage):
        return {"prospect_id": store.add_evidence(item.name, item.source, item.body)}

    @app.post("/api/snapshot")
    async def snapshot(item: Snapshot):
        from .research import render_saved_html
        try:
            body = await render_saved_html(item.html)
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        except Exception as exc:
            raise HTTPException(503, "Snapshot rendering failed. Install Playwright Chromium or paste the page text.") from exc
        return {"prospect_id": store.add_evidence(item.name, item.source, body)}

    @app.post("/api/capture")
    async def collect(item: PublicPage):
        if offline:
            raise HTTPException(409, "Public website capture is disabled in offline mode.")
        if not item.permitted:
            raise HTTPException(422, "Confirm that the website permits this capture.")
        from .research import capture
        try:
            url, body = await capture(item.url)
        except (httpx.HTTPError, ValueError, TimeoutError) as exc:
            raise HTTPException(422, f"Could not capture the public page. {exc}") from exc
        return {"prospect_id": store.add_evidence(item.name, url, body)}

    @app.post("/api/demo")
    def demo():
        seed = json.loads((HERE / "demo.json").read_text(encoding="utf-8"))
        for value in seed["products"]:
            item = Product.model_validate(value)
            store.write(
                """INSERT INTO products(company, name, brief, exclusion_phrases)
                   VALUES (?, ?, ?, ?)
                   ON CONFLICT(company, name) DO UPDATE SET exclusion_phrases = excluded.exclusion_phrases
                   WHERE products.brief = excluded.brief AND products.exclusion_phrases = ''""",
                (item.company, item.name, item.brief, item.exclusion_phrases),
            )
        for value in seed["evidence"]:
            item = ManualPage.model_validate(value)
            store.add_evidence(item.name, item.source, item.body)
        return {"reply": seed["reply"]}

    @app.post("/api/jobs", status_code=202)
    def start(run: Run):
        if run.model not in MODELS:
            raise HTTPException(422, "Choose an approved local Qwen3 model.")
        products = store.rows("SELECT * FROM products WHERE id = ?", (run.product_id,))
        if not products:
            raise HTTPException(404, "Product not found.")
        inputs = {"product": products[0], "reply": run.reply.strip(), "steps": ["profile", "icp"]}
        if run.prospect_id is not None:
            prospects = store.rows("SELECT * FROM prospects WHERE id = ?", (run.prospect_id,))
            if not prospects:
                raise HTTPException(404, "Prospect not found.")
            inputs["prospect"] = prospects[0]
            inputs["evidence"] = store.rows(
                "SELECT id, source, body FROM evidence WHERE prospect_id = ? ORDER BY id DESC LIMIT 12",
                (run.prospect_id,),
            )
            inputs["steps"].extend(["research", "signals", "problem", "score", "draft"])
        if inputs["reply"]:
            inputs["steps"].append("reply")
        job_id = store.write("INSERT INTO jobs(product_id, prospect_id, model, input) VALUES (?, ?, ?, ?)",
                             (run.product_id, run.prospect_id, run.model, json.dumps(inputs)))
        return {"id": job_id}

    @app.get("/api/jobs/{job_id}")
    def inspect(job_id: int):
        rows = store.rows("SELECT * FROM jobs WHERE id = ?", (job_id,))
        if not rows:
            raise HTTPException(404, "Run not found.")
        row = rows[0]
        row["input"] = json.loads(row["input"])
        row["results"] = {k: v for k, v in json.loads(row["results"]).items() if not k.startswith("_")}
        row["logs"] = store.rows("SELECT * FROM inference WHERE job_id = ? ORDER BY id", (job_id,))
        return row

    @app.post("/api/jobs/{job_id}/retry", status_code=202)
    def retry(job_id: int):
        rows = store.rows(
            """UPDATE jobs SET status = 'queued', error = NULL, resume_at = 0
               WHERE id = ? AND status IN ('waiting', 'failed') RETURNING id""",
            (job_id,),
        )
        if not rows:
            raise HTTPException(409, "Only waiting or failed runs can be retried.")
        return rows[0]

    return app
