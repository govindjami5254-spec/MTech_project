# Archive: files preserved from outside the project folders

These files were created during the project but stored outside the repository folders. They are kept here only
for completeness. None of them is used by the current code or by the dissertation's experiment.

| Path | Origin | What it is |
|---|---|---|
| `prototype-eval-tmp/agentrca_eval_*` | `/tmp/agentrca_eval_*`, 2026-11-19 | Scratch output of the early AgentRCA prototype evaluation (`agentrca/eval.py`): generated synthetic scenarios and run reports. Superseded by `data/eval_run1` and later by LogAgent-RCA. Some reports come from the period when Ollama was down (all-zero scores). |
| `ollama/smoke.py` | `/home/zjamgov/ollama/smoke.py`, 2026-11-19 | Ollama/model smoke test used when choosing and installing the model (qwen3:8b, llama3.1:8b) |
| `ollama/serve.log` | `/home/zjamgov/ollama/serve.log` | Ollama server log covering the pilot, the operational check and the interrupted test run, up to 2026-11-26 08:55 IST |

The synthetic logs include deliberately planted fake credentials and e-mail addresses, such as
`user=jdoe@example.com password=hunter2`. They exist to test log sanitisation and redaction. They are not real
credentials.
