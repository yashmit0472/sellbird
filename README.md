# Sellbird Local

An offline sales research and outreach workspace built for the EDXSO assignment. It extends [Sellbird, formerly Harvey](https://github.com/ethanplusai/sellbird), with a Windows dashboard for comparing how different products fit the same prospect.

## Run on Windows

Install [Python 3.14](https://www.python.org/downloads/windows/) and [Ollama](https://ollama.com/download/windows). Clone this fork and run the setup script once from the repository folder. Setup uses the internet to install dependencies and download the Qwen3 and MiniLM model files.

```powershell
git clone https://github.com/yashmit0472/sellbird.git
cd sellbird
powershell -ExecutionPolicy Bypass -File .\scripts\local-setup.ps1
```

For each session, start the dashboard and the dedicated Ollama daemon together with the launcher. The following command uses the CPU profile tested on the assignment laptop.

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\local-run.ps1 -Offline -CpuOnly
```

Open the private dashboard URL printed in the terminal and keep its token private. The dashboard listens on `127.0.0.1:8765`, and Ollama listens on `127.0.0.1:11435`. The default model is `qwen3:1.7b`. Local inference requires no API keys, account, or token billing.

## How the offline version works

| Component | What changed |
| --- | --- |
| Model inference | The launcher starts a dedicated Ollama process on loopback, disables its cloud features, and checks startup before enabling inference. The FastAPI worker sends Qwen3 requests only to that local endpoint. |
| Evidence retrieval | Sentence Transformers loads pinned MiniLM weights from disk in local-only mode. The worker ranks passages from saved evidence and checks model quotes against the retrieved text. |
| Local persistence | SQLite stores products, prospects, evidence, run inputs, step results, and inference logs. Completed stages are checkpointed, and interrupted jobs can resume. |
| Offline mode | The dashboard blocks public-page capture and the app rejects external Python socket connections. Pasted text and saved HTML remain available for local research. |
| Daemon failure | If Ollama becomes unavailable, jobs wait with a visible error. Product setup, evidence imports, and previous results remain accessible. |

## Run the sales workflow

1. In **Workspace setup**, use **Add or update a product** to enter the seller, product name, and product brief. Use **Add prospect evidence** to save source text or an authorized HTML snapshot.
2. Under **New run**, select the product, prospect, and model. Paste an email-and-reply conversation to include reply classification.
3. Queue the run and open its results. A full run generates a business profile, product-specific ideal customer profile (ICP), prospect research, buying signals, a problem hypothesis, a score, an email draft, and a reply classification.
4. Use **Latest score ranking** to compare the latest completed scores by product and prospect. Scores combine fit, intent, and evidence quality. A configured exclusion phrase found in saved evidence sets fit and intent to zero and identifies the matching source.

The workspace produces drafts for review. Treat inferred buying intent and problem statements as hypotheses and verify them against the cited evidence.

## Verify the offline workflow

1. Run the complete workflow once while connected, using manually saved entries. The [sample fixture](sellbird/local/demo.json) provides two products, prospect evidence, and a sample reply for a repeatable test.
2. Disconnect Wi-Fi and Ethernet, leave the dashboard open, and queue a **new run** with the same inputs. Confirm all eight stages complete.
3. Open **Local inference logs** for the new run. Check the model name, successful stages, and `http://127.0.0.1:11435` endpoint. Compare the same prospect against a second product to show prioritisation.

The [test evidence](docs/local-test-evidence.md) records two completed runs in application offline mode. The separate network-disconnection check above demonstrates that the workflow can run with the computer disconnected.

See the [technical guide](docs/local-assignment.md) for model options, failure recovery, and the automated acceptance recorder, and the [dependency inventory](docs/local-dependencies.md) for component versions and licenses.

## License

See [LICENSE](LICENSE) and [NOTICE](NOTICE) for the fork’s AGPL-3.0 terms and upstream attribution.
