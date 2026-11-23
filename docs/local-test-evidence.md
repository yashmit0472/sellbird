# Local test evidence

The final dashboard test ran on Windows with Python 3.14.2, CPU-mode Ollama 0.40.16, Qwen3 1.7B and cached MiniLM embeddings. The fixture companies, website text and replies are fictional. Ollama generated the analysis and drafts during the run.

| Product | Run | Stages completed | Score | Model endpoint |
| --- | --- | --- | --- | --- |
| RouteDesk | 8 | 8/8 | 66/100 | `http://127.0.0.1:11435` |
| RenewalDesk | 9 | 8/8 | 20/100 | `http://127.0.0.1:11435` |

Both runs used the same prospect. The RenewalDesk score identified the exclusion in saved source #1 and set fit and intent to zero. Both runs classified the sample reply as interested.

The 11:14 recording, detailed JSON and screenshots are in `data/local/acceptance/offline`. Open `assignment-demo.webm` for the 8:59 version at 1.25× playback and the two `*-trace.png` files for the model logs.

Nine automated tests passed. The test run also verified that cached MiniLM ranked a relevant passage first and that local Chromium extracted a saved HTML fixture with external requests and scripts disabled.

The dashboard ran in application offline mode. Public capture was blocked, the recorder allowed only loopback page requests, and the Ollama daemon reported cloud features disabled. The assignment's physical Wi-Fi and Ethernet disconnection check is still pending. The setup guide includes the steps to repeat it.
