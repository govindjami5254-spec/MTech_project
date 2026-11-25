# LogAgent-RCA — Web application and CLI guide

LogAgent-RCA diagnoses the root cause of an incident from log files using a local language model (Ollama). It is a
**read-only** assistant: it never executes commands, changes systems or remediates. The web application and the CLI
are two interfaces to **the same** backend services and RCA engine.

## 1. Architecture

```
  Browser ──HTTP(127.0.0.1)──► FastAPI adapter (logagent_rca/web)        CLI (python -m logagent_rca ...)
                                │  pages, JSON API, auth, CSRF, uploads      │  diagnose / investigations / report / serve
                                │  background worker (1 analysis at a time)  │
                                └──────────────────┬─────────────────────────┘
                                                   ▼
                          Shared application services  (logagent_rca/service.py)
                          validate uploads + incident ─ build case bundle ─ queue/run analysis
                          progress ─ history ─ evidence tracing ─ health ─ dashboard
                                                   │
                                                   ▼
                          Existing RCA engine, unchanged:  runner.run_one
                          ingest/index ─ evidence ledger (strict budget B) ─ E2b (extract + 1 call)
                          E3 (agent loop + read-only tools + coverage gate) ─ finalize ─ grounding validator
                                                   │
                     ┌─────────────────────────────┴───────────────────────────┐
                     ▼                                                         ▼
     File-based persistence (logagent_rca/store.py)            Ollama 127.0.0.1:11434, qwen3:8b
     workspace/cases, workspace/investigations                  (llm.OllamaClient, prompts.py)
```

Research tooling (`python -m logagent_rca run | analyze`, `configs/test.yaml`, `results/`) is separate and unchanged.

## 2. What is shared (and how it is enforced)

| Concern | Single implementation |
|---|---|
| RCA execution | `runner.run_one` (same function the research experiment uses) |
| E2b / E3, tools, coverage gate, validator, prompts | existing modules, imported unchanged |
| Model and parameters, evidence budget, agent limits, safety, ingestion | `configs/app.yaml`; a test asserts these sections equal `configs/test.yaml` |
| Ollama access | `llm.OllamaClient` |
| Persistence | `store.InvestigationStore` (used by CLI and web) |
| Report rendering | `report_render.build_view` / `to_markdown` (web page, downloads, CLI output) |
| Equivalence | test `test_cli_and_web_produce_identical_reports`: same inputs → same validated report and evidence |

## 3. Installation

Requirements: Python 3.12, Ollama with `qwen3:8b` installed (already present on the development server at
`/home/zjamgov/ollama`), and the verified Qwen3 tokenizer file.

```bash
cd /home/zjamgov/kiro-web                      # or your clone of branch feature/logagent-rca-web
python3.12 -m venv .venv
.venv/bin/python -m pip install -r requirements-logagent.txt -r requirements-web.txt
mkdir -p models
curl -L -o models/qwen3-tokenizer.json \
  https://huggingface.co/Qwen/Qwen3-8B/resolve/b968826d9c46dd6066d109eabc6255188de91218/tokenizer.json
sha256sum models/qwen3-tokenizer.json   # must be aeb13307a71acd8fe81861d94ad54ab689df773318809eed3cbe794b4492dae4
```

Start Ollama if it is not running (development server):

```bash
cd /home/zjamgov/ollama && OLLAMA_MODELS=$PWD/models OLLAMA_HOST=127.0.0.1:11434 nohup ./install/bin/ollama serve > serve.log 2>&1 &
```

## 4. Web application

### Start

```bash
cd /home/zjamgov/kiro-web
./scripts/start_web.sh                          # = .venv/bin/python -m logagent_rca serve --host 127.0.0.1 --port 8765
```

Open **http://127.0.0.1:8765/** in a browser on the same machine. To use it from another computer, tunnel instead of
exposing the port: `ssh -L 8765:127.0.0.1:8765 <user>@<server>` and open http://127.0.0.1:8765/ locally.

### Pages

| Page | URL | Purpose |
|---|---|---|
| Dashboard | `/` | Counts and recent investigations from stored data; median wall time per mode |
| New analysis | `/new` | Upload logs, enter incident and trigger, choose E2b or E3, start |
| Investigation | `/investigations/<id>` | Progress events, RCA report, evidence tracing, downloads, re-run in the other mode |
| History | `/investigations` | Filter by incident ID, mode and date; open reports; download Markdown/JSON |
| Settings & health | `/settings` | Ollama status and models, configured model and parameters, budget, persistence, tokenizer (read-only) |

### Input requirements

* Files: `.log` or `.txt`; up to 20 files, 20 MB and 200,000 lines each, 100 MB in total; no binary content.
  Names are reduced to their base name and safe characters.
* Line format: `<timestamp> <LEVEL> <component> <message>`, e.g. `2026-01-10T10:04:48Z ERROR db-primary write failed`.
  Indented lines (stack traces) are attached to the previous event.
* Incident ID: `INC-` followed by 3–6 digits. Description: up to 200 characters. Time: with time zone.
* Trigger: the file and 1-based line number of the event that reported the incident, and its component. The page
  previews the line and pre-fills the component from it. The line must lie between 600 s before and 120 s after the
  incident time.

### What the progress panel shows

Only events the backend records: input validation, ingestion statistics, queueing, start (mode, model, budget), the
agent's tool calls with evidence-budget use, refused tool requests, coverage-gate decisions, prompt-injection flags,
report validation and completion. E2b performs a single model call and records no intermediate steps. No percentages
are shown because the backend does not know how long a model call will take.

### Reading the report

* Hypotheses are ranked as the model ranked them. **Confidence** is the model's self-assessed score (0–1); it is not a
  calibrated probability.
* Every claim lists its evidence IDs; each evidence item shows the source file, line number, time and the message as
  presented to the model. *source* opens the original lines of the uploaded file around that line.
* **Grounding validation** shows how many claims were supported, fabricated evidence IDs, and the claims the validator
  removed. Arms are reported on the validated report.
* Recommendations are advisory text for a human; they are never executed and their quality is not evaluated.

## 5. CLI

```bash
# Diagnose one incident (same engine and persistence as the web UI)
.venv/bin/python -m logagent_rca diagnose \
  --log /path/api-gateway.log --log /path/db-primary.log \
  --incident-id INC-001 --description "Entry service returned 5xx errors" \
  --time 2026-01-10T10:05:05Z --trigger-file api-gateway.log --trigger-line 42 \
  --trigger-component api-gateway --mode E3            # or --mode E2b

.venv/bin/python -m logagent_rca investigations [--incident-id INC-001] [--mode E3]
.venv/bin/python -m logagent_rca report --investigation inv-YYYYMMDD-xxxxxxxx [--run <run_id>] [--format md|json]
.venv/bin/python -m logagent_rca serve [--host 127.0.0.1] [--port 8765] [--auth-file users.json]

# Research commands (unchanged)
.venv/bin/python -m logagent_rca run --config configs/test.yaml
.venv/bin/python -m logagent_rca analyze --config configs/test.yaml
```

Investigations created by the CLI appear in the web history and vice versa.

## 6. API (JSON, same origin)

| Method | Path | Notes |
|---|---|---|
| GET | `/api/health`, `/api/models`, `/api/dashboard` | Read-only system information |
| POST | `/api/incidents` | multipart: `files[]`, `incident_id`, `description`, `timestamp`, `trigger_file`, `trigger_line`, `trigger_component`, optional `rule_id`, optional `mode` (queues analysis) → 201 |
| POST | `/api/incidents/{id}/analyze` | JSON `{"mode": "E2b"|"E3"}` → 202 (queued); 409 if one is already queued/running |
| GET | `/api/incidents` | filters `incident_id`, `mode`, `date_from`, `date_to` |
| GET | `/api/incidents/{id}`, `/status?run_id=`, `/report?run_id=`, `/report.md`, `/report.json`, `/evidence`, `/evidence/{eid}/source` | |

Validation errors return 422 with `{"detail": ..., "errors": {field: message}}`. All state-changing requests need the
anti-CSRF header (`X-Requested-With: logagent-rca` in local mode, `X-CSRF-Token` with login).

## 7. Persistence

No database. Everything is stored as files under `workspace/` (git-ignored):

```
workspace/cases/<inv-id>/incident.json + uploaded logs     case bundle (the format the engine reads)
workspace/investigations/<inv-id>/meta.json               incident, files (size, lines, SHA-256), analyses + status
workspace/investigations/<inv-id>/events.jsonl            application progress events
workspace/investigations/<inv-id>/runs/<run>.json          full RunRecord: raw + validated report, evidence, metrics, provenance
workspace/investigations/<inv-id>/audit/<run>.jsonl        tool calls, refusals, gate decisions, injection flags
workspace/investigations/<inv-id>/transcripts/<run>.json   all messages exchanged with the model
```

Run records are never overwritten: analysing again creates `r1`, `r2`, … with seed `1000 + repeat`. Records carry the
code commit, config hash and model digests.

## 8. Model and Ollama configuration

`configs/app.yaml` (read-only from the web): `qwen3:8b`, temperature 0.2, no thinking, context 8,192, max 450 output
tokens per call, evidence budget B = 900 tokens, max 6 agent steps, coverage gate on, validator on. These equal the
frozen research configuration (`configs/test.yaml`) and must not be edited. Only one analysis runs at a time (Ollama
uses one parallel slot); a file lock also serialises CLI and web.

**Protection of research runs:** an analysis is refused while a research experiment (`python -m logagent_rca run`) is
running on the same host, so that it cannot disturb the experiment's measurements.

## 9. Authentication and security

* **Default: local mode** — no login, bound to 127.0.0.1 only; the server refuses a non-loopback `--host` without
  `--auth-file`. Host headers other than localhost are rejected (DNS-rebinding protection).
* **Users mode** — create users, then start with the file:
  ```bash
  .venv/bin/python -m logagent_rca.web.auth add-user --file users.json --username alice --role analyst
  .venv/bin/python -m logagent_rca serve --auth-file users.json
  ```
  Roles: `viewer` (read own), `analyst` (create/analyse, read own), `admin` (read all). Passwords: PBKDF2-SHA256,
  240,000 iterations, minimum 12 characters. Sessions: HMAC-signed, HttpOnly, SameSite=Strict cookies valid for 8 h
  (invalidated on restart). Users cannot see each other's investigations.
* Uploads: size, count and line limits; name sanitising; binary rejection; storage only inside the workspace;
  identifiers validated; no path from a request is used without containment checks.
* Log content is untrusted: sanitised and wrapped for the model, instruction-like lines flagged, flagged lines never
  support a claim; the browser renders all log-derived text as plain text. Content-Security-Policy forbids inline and
  third-party scripts.
* No command execution, SSH, file browsing or settings changes are available through the application.
* **The language model is not a security boundary.** Controls are enforced in code.
* **Before any external exposure:** run behind a reverse proxy with TLS, keep the app bound to 127.0.0.1, use users
  mode, restrict access by network policy, and back up `workspace/`.

## 10. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| Settings: Ollama not reachable | Start Ollama (Section 3); check `llm.base_url` |
| Analysis status `error: refused: the research experiment is running` | Wait until the experiment finishes |
| `trigger_line: trigger event … not found` | The line does not match the log format or the number is wrong; check the preview |
| `timestamp: … outside the analysis window` | The incident time must be at most 600 s after and at most 120 s before the trigger line |
| `tokenizer sha256 … != expected` | Re-download the tokenizer file (Section 3) |
| Analysis takes many minutes | Expected on CPU-only hardware (development measurements: ~8 min E2b, ~12 min E3) |
| Status stuck at `running` after a crash | On restart the worker marks it `error: interrupted`; start a new analysis |

## 11. Tests

```bash
.venv/bin/python -m pytest -q                      # all tests; the application suite uses a scripted LLM
.venv/bin/python scripts/smoke_web.py              # start the real server in-process, check pages/health, stop
```

No automated test performs Ollama inference. A real end-to-end check (`diagnose` on a development case) should be run
only when no research experiment is running.
