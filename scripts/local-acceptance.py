"""Exercise all eight steps in the dashboard and record model-generated evidence."""

import argparse
import json
import os
import re
from pathlib import Path

import httpx
from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[1]
os.environ.setdefault("PLAYWRIGHT_BROWSERS_PATH", str(ROOT / "data/local/browsers"))
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--online", action="store_true", help="Record a baseline before the disconnected run.")
parser.add_argument("--model", default="qwen3:1.7b")
parser.add_argument("--record", action="store_true")
parser.add_argument("--port", type=int, default=8765)
args = parser.parse_args()
data = Path(os.environ.get("SELLBIRD_LOCAL_DATA", ROOT / "data/local")).resolve()
output = data / "acceptance" / ("baseline" if args.online else "offline")
output.mkdir(parents=True, exist_ok=True)

base = f"http://127.0.0.1:{args.port}"
token = (data / "dashboard-token").read_text(encoding="ascii").strip()
headers = {"Authorization": "Bearer " + token}
rejected = []

with httpx.Client(base_url=base, headers=headers, trust_env=False) as api:
    status = api.get("/api/status").raise_for_status().json()
    assert status["offline"] != args.online, "Use the launcher mode that matches this run."
    assert status["ollama"] and args.model in status["installed"], "The selected model must be installed."
    if not args.online:
        capture = api.post("/api/capture", json={"name": "Example", "url": "https://example.com", "permitted": True})
        assert capture.status_code == 409, "Offline mode should refuse public capture."

    seed = api.post("/api/demo", json={}).raise_for_status().json()

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(args=["--no-proxy-server"])
        recording = {"record_video_dir": output, "record_video_size": {"width": 1280, "height": 800}} if args.record else {}
        ctx = browser.new_context(viewport={"width": 1280, "height": 800}, service_workers="block", **recording)

        def local_only(route):
            if route.request.url.startswith(base + "/"):
                route.continue_()
            else:
                rejected.append(route.request.url)
                route.abort()

        ctx.route("**/*", local_only)
        page = ctx.new_page()
        video = page.video
        try:
            page.goto(base + "/#token=" + token)
            page.locator("#start textarea[name=reply]").fill(seed["reply"])
            fixture = api.get("/api/workspace").raise_for_status().json()
            prospect = next(item for item in fixture["prospects"] if item["name"] == "Northline Heating")
            runs = []
            for product_name in ("RouteDesk", "RenewalDesk"):
                product = next(item for item in fixture["products"] if item["name"] == product_name)
                page.locator('select[name=product_id]').select_option(str(product["id"]))
                page.locator('select[name=prospect_id]').select_option(str(prospect["id"]))
                page.locator('select[name=model]').select_option(args.model)
                with page.expect_response(lambda response: response.url == base + "/api/jobs" and
                                          response.request.method == "POST") as started:
                    page.get_by_role("button", name="Queue run").click()
                job_id = started.value.json()["id"]
                print(f"Queued {product_name} as run {job_id}.", flush=True)
                page.locator("#result-title").get_by_text(f"Run #{job_id} · {product_name}").wait_for()
                page.locator("#result-status").get_by_text(
                    re.compile(r"^(Complete|Failed|Waiting)")
                ).wait_for(timeout=720_000)
                job = api.get(f"/api/jobs/{job_id}").raise_for_status().json()
                (output / f"{product_name}.json").write_text(json.dumps(job, indent=2, ensure_ascii=False), encoding="utf-8")
                assert job["status"] == "complete", f"{product_name}: {job['status']} {job['error']}"
                assert len(job["results"]) == 8, "All eight stages must return data."
                assert {entry["step"] for entry in job["logs"] if entry["status"] == "ok"} == set(job["results"])
                assert {entry["endpoint"] for entry in job["logs"]} == {status["endpoint"]}
                print(f"{product_name}: {job['results']['score']['total']}/100, eight stages complete.", flush=True)
                runs.append(job)
                for summary in page.locator("#steps summary").all():
                    summary.scroll_into_view_if_needed()
                    if summary.locator("..").get_attribute("open") is None:
                        summary.click()
                    if args.record:
                        page.wait_for_timeout(2200)
                logs = page.get_by_text("Local inference logs")
                logs.click()
                logs.scroll_into_view_if_needed()
                page.locator("#logs").screenshot(path=output / f"{product_name}-trace.png")
                logs.click()
                page.locator('[data-step="draft"]').screenshot(path=output / f"{product_name}-draft.png")
                page.locator("#start").scroll_into_view_if_needed()
            assert not rejected, f"Unexpected external browser requests: {rejected}"
            assert runs[0]["results"]["draft"]["body"] != runs[1]["results"]["draft"]["body"]
            assert runs[0]["results"]["score"]["total"] > runs[1]["results"]["score"]["total"], (
                "The same prospect should score higher for the product that matches its operating needs."
            )
            assert all(run["results"]["reply"]["label"] == "interested" for run in runs)
            print(f"Acceptance evidence saved in {output}.", flush=True)
        finally:
            ctx.close()
            if video:
                video.save_as(output / "dashboard-demo.webm")
                video.delete()
            browser.close()
