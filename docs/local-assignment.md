# Sellbird Local

This fork adds a single-user sales workspace for the EDXSO local AI assignment. Start it with the local launcher below. It uses Sellbird's loopback dashboard authentication and public-site HTTP transport. The original Sellbird commands remain available to legacy users and have their own dependencies and configuration.

## Windows setup

Install [Python 3.14](https://www.python.org/downloads/windows/) and [Ollama](https://ollama.com/download/windows). From a checkout of the fork:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local-setup.ps1
powershell -ExecutionPolicy Bypass -File .\scripts\local-run.ps1
```

Open the URL printed by the launcher. The fragment contains a dashboard token. Keep it private. First setup needs network access for packages, Chromium, MiniLM and the selected Qwen3 weights. The launcher starts an Ollama daemon at `127.0.0.1:11435` with cloud features disabled and verifies the daemon log before treating it as ready. The app listens on `127.0.0.1:8765`. Store files are under `data/local`.

The default model is `qwen3:1.7b`. On the tested 7.8 GiB laptop with a GTX 1650, launch with `-CpuOnly`. GPU inference stalled on that system. Try `qwen3:4b` on a laptop with more free memory or VRAM. On a machine with at least 8 GiB VRAM and 16 GiB system RAM, try the `8b` profile. A higher-memory GPU can use `14b`. These are starting estimates. Context and other processes affect actual requirements. The dashboard reports installed models, CPU count, free and total RAM, and NVIDIA VRAM if `nvidia-smi` is available. CPU inference is supported. Pass `-CpuOnly` to the run script if GPU inference stalls. Set `$env:SELLBIRD_LOCAL_CPU_ONLY='1'` in PowerShell before starting the setup or app if GPU detection fails. Pass `-Model 'qwen3:4b'` to the setup script to download another supported size.

## Workflow

1. Under **Workspace setup**, use **Add or update a product** to save your company and product brief. Select a product for each run. Optionally set one exact disqualifying phrase per line for an explicit product prerequisite.
2. Paste prospect evidence or import saved HTML. When connected, you can also explicitly capture a permitted public page. The source label or URL is saved with the evidence.
3. Select a prospect, choose the installed model, and optionally paste a reply with conversation context.
4. Queue a run. Profile and ICP generation happen first. Prospect runs add research, signals, a problem hypothesis, a score and a draft. A supplied reply is classified in the last step.
5. Choose Latest score ranking to rank the most recent completed score for each product and prospect. Open each run to review the component scores, exact source quotes, draft, and inference logs.

## Architecture and failure handling

The dashboard and FastAPI backend run on loopback. SQLite holds product briefs, prospect evidence, immutable input snapshots, job progress and inference logs. The worker runs one job at a time and checkpoints each stage. An interrupted process requeues its running job on restart. When Ollama is missing or unreachable, the job waits and retries after 45 seconds. You can retry from its detail view. If the launcher cannot verify the daemon at startup, it opens the dashboard with inference paused. Restart the launcher to resume those jobs after resolving the daemon problem. Importing, editing products, and reading previous results work without Ollama. A workspace lock prevents two processes from starting workers against the same database.

Sentence Transformers encodes saved evidence with a pinned MiniLM model on CPU. It reads safetensors from disk and uses local-only, telemetry-disabled loading. The worker sends shortlisted passages with each relevant prompt. Qwen returns typed JSON via the local Ollama API. Evidence quotes are checked against supplied text. The application combines fit, intent, and evidence quality. Intent points are capped by the buying-signal classification. The result shows both the model's proposed intent points and the cap. If saved evidence contains a configured disqualifying phrase, the score shows the matching source and awards zero fit and intent points. Evidence quality retains its own score. A problem statement is a hypothesis for a salesperson to validate.

Public capture is an explicit import action. It uses Sellbird's public-IP HTTP transport, checks robots rules per target, and parses bounded static HTML with Scrapy and Beautiful Soup. Saved HTML can be processed in Playwright Chromium with JavaScript and external requests disabled. For public capture, the operator is responsible for permission. Sites requiring authentication or live JavaScript are outside this capture workflow. Use an authorized saved snapshot if available.

## Offline acceptance

1. Run the normal launcher, save a product and prospect evidence using the workspace forms, and queue a full run. For a reproducible example, use RouteDesk and Northline Heating from the [sample fixture](../sellbird/local/demo.json). Paste the fixture conversation to include reply classification.
2. Close the launcher, disconnect Wi-Fi and Ethernet, and start `powershell -ExecutionPolicy Bypass -File .\scripts\local-run.ps1 -Offline`. Leave loopback enabled. Offline mode rejects public capture and external Python socket connections. The launcher starts the cloud-disabled daemon with external HTTP proxy traffic blocked at process scope.
3. Repeat the eight steps from the browser. Try the same prospect with RenewalDesk to show how the product changes the analysis. Open **Local inference logs** and verify the model name, loopback URL, timings and token counts. Reconnect after recording.
4. To automate the dashboard portion, run `\.venv314\Scripts\python.exe scripts/local-acceptance.py --record` against the offline launcher. Evidence and the browser recording go to `data/local/acceptance/offline`. This script restricts browser requests to the local dashboard. Disconnecting the computer's external network is a separate manual step. Use `--online` for a baseline.

Test the missing-daemon path by running `\.venv314\Scripts\python.exe -m sellbird.local --offline` while the assignment's Ollama daemon is stopped. Queue a job and verify its waiting message. Stop that dashboard and restart with the launcher to allow processing. Run automated checks with `\.venv314\Scripts\python.exe -m pip install pytest` followed by `\.venv314\Scripts\python.exe -m pytest -q local_tests`.

## Cost and licenses

Local model calls require no API key, subscription, external inference service, or token billing. Output token counts measure work performed by the local model. Setup downloads require bandwidth and disk. Local execution consumes system resources and power. Public page discovery and capture require network access only during collection. This workflow has no paid enrichment or verification integration.

| Component | License |
| --- | --- |
| Sellbird fork | AGPL-3.0-only. See the repository LICENSE and NOTICE. |
| Python | PSF-2.0 |
| SQLite | Public domain |
| Ollama | MIT |
| Qwen3 1.7B, 4B, 8B, 14B | Apache-2.0 |
| Sentence Transformers, Transformers, Hugging Face Hub, all-MiniLM-L6-v2 | Apache-2.0 |
| PyTorch | BSD-3-Clause |
| FastAPI, Pydantic, Beautiful Soup | MIT |
| psutil, Protego | BSD-3-Clause |
| Uvicorn, HTTPX, Scrapy | BSD-3-Clause |
| Playwright | Apache-2.0. Chromium has a BSD license and third-party notices. |

See [Python dependency inventory](local-dependencies.md) for the resolved Windows test environment, including transitive packages. Model sources are [Qwen3](https://ollama.com/library/qwen3) and [MiniLM](https://huggingface.co/sentence-transformers/all-MiniLM-L6-v2).

## Scope and limitations

- Sample companies, site text and replies are fictional. The model generates the workflow outputs from these inputs.
- The app drafts email and classifies supplied replies. It does not send email or connect to a mailbox.
- Prospect collection starts from an operator-supplied company and URL. It does not discover companies across the open web.
- Model-generated summaries, classifications and scores can be wrong. Evidence citations validate quoted text, and a person should review conclusions before acting. In the demo, the small model inferred an intention to replace spreadsheets from a job posting that only established their current use. Larger supported models may improve results.
- This submission targets a documented local installation. The dashboard token protects local access, and the server is not configured for public hosting.
