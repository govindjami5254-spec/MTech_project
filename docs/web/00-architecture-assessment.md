# M0 — Architecture assessment and implementation plan (LogAgent-RCA web + CLI)

Branch `feature/logagent-rca-web`, created from `logagent-rca` at `c5448ef` (`test-freeze`) as a **separate git
worktree** (`/home/zjamgov/kiro-web`) with its own virtual environment. The frozen tree (`/home/zjamgov/kiro`),
its `.venv`, and `results/test-main` are not touched; the running experiment imports its code from the frozen tree.

## 1. Existing architecture (as found)

| Layer | Modules | Notes |
|---|---|---|
| Contracts | `schemas.py` | Pydantic: `LogEvent`, `Evidence`, `Incident`, `CaseManifest`, `GroundTruth`, `FinalReport`, `ModelInfo`, `ToolCallRecord`, `RunMetrics`, `ValidationStats`, `RunRecord`, enums `ArmId`, `Split`, `Stratum`, `RunStatus` |
| Configuration | `config.py`, `configs/*.yaml` | Frozen sections; `load_config(path, overrides)`, `config_hash`; data-directory disjointness; budget fits context |
| Ingestion | `ingest.py`, `index.py` | Manifest-listed files only, containment, bounded reads, sanitising, redaction, injection flag; read-only `LogIndex` |
| Tokens / evidence | `tokens.py`, `evidence.py` | Verified Qwen3 tokenizer; canonical evidence line; `EvidenceLedger` (strict B, repeats recorded) |
| Arms | `e1.py`, `extract.py`, `e2b.py`, `agent.py`, `coverage.py`, `tools.py`, `safety.py` | E1/E1f rules; E2b packing + one call; E3 loop, gate, read-only tools, allowlist, audit |
| LLM | `llm.py`, `prompts.py`, `finalize.py` | Standard-library Ollama client (`/api/chat`, `/api/tags`, `/api/show`, `/api/version`), shared prompts and schema, normalisation, one retry |
| Validation | `validator.py` | Claim-level grounding; raw report preserved |
| Orchestration | `runner.py` | `run_one(cfg, case_id, arm, rep, out, llm, counter, cache, commit)` executes one arm on one case bundle and writes the run record, audit log, transcript and index; `run_experiment` loops over cases × arms × repeats with integrity checks |
| Scoring | `metrics.py`, `stats.py`, `analyze.py` | Read ground truth; research only |
| Measurement | `resources.py` | Ollama process-tree CPU/memory |
| CLI | `__main__.py` | `run` (experiment) and `analyze` (scoring) only |
| Data generation | `synth/`, `truth.py` | Research data only |

**There is no database.** Persistence is file-based: case bundles (`incident.json` + logs) and, per output
directory, `runs/<run_id>.json` (complete `RunRecord`), `audit/<run_id>.jsonl`, `transcripts/<run_id>.json`,
`index.jsonl`, `config.json`.

**No standalone diagnosis interface exists**; a single incident can only be run through `run` with config
overrides and a hand-written `incident.json`. There is no incident detection and no human-readable report renderer.

## 2. Execution path: CLI input → validated report

```
python -m logagent_rca run --config C [--cases] [--arms] [--set]
 → config.load_config(C, overrides)           validated Config
 → runner.run_experiment                      verify_split, git commit, case list, planned_runs
   → runner.run_one(cfg, case, arm, rep, out, llm, counter, cache, commit)
       → context.open_case                    ingest.load_case → LogIndex
       → OllamaClient.model_info              provenance
       → ResourceSampler                      CPU/memory
       → e2b.run_e2b | agent.run_e3(+coverage.make_gate) | e1.run_e1
            evidence.EvidenceLedger, extract.pack / tools.ToolRegistry, finalize.request_final
       → validator.validate_report            validated report + ValidationStats
       → RunRecord → runs/<run_id>.json (atomic), audit, transcript, index.jsonl
```

## 3. Reuse assessment

* `runner.run_one` is already interface-independent: it needs a config, a case bundle directory, an arm and an
  output directory. **It will be reused unchanged as the only execution path** for both CLI and web diagnosis.
  Therefore E2b, E3, tools, gate, validator, prompts, model client, token budget and record format are identical
  by construction.
* No existing module needs refactoring. All work is additive:
  - `logagent_rca/store.py` — investigation store over the existing file layout (bundle + run output + small
    metadata/event files); no database.
  - `logagent_rca/service.py` — shared application services (create investigation from uploaded files, analyse,
    list, load report, health) used by both CLI and web.
  - `logagent_rca/report_render.py` — pure function `RunRecord → Markdown/view model` (used by CLI and web).
  - `__main__.py` — additive subcommands (`diagnose`, `investigations`, `report`, `serve`); `run`/`analyze`
    unchanged.
  - `logagent_rca/web/` — FastAPI adapter, background job worker, auth, templates, static assets.
  - `configs/app.yaml` — application config with **the same model, budget, agent, validator, safety and ingestion
    settings as `configs/test.yaml`** (enforced by test), but its own workspace directories.

## 4. Decisions and their rationale

| Decision | Reason |
|---|---|
| Separate git worktree + venv | Branch switching or package changes in the frozen tree could affect a resumed experiment |
| File-based store, no database | Matches existing persistence; no migration; records stay readable by the existing `RunRecord` model |
| Workspace `workspace/` (git-ignored) with `cases/`, `investigations/`, `no-truth/` | Uses existing config disjointness rules; never inside `results/` |
| FastAPI + Jinja2 server-rendered pages + small vanilla JS (no CDN) | Thin adapter, works offline, Python-only stack; FastAPI pinned 0.165.0 |
| Single analysis worker + cross-process lock | Ollama runs with one parallel slot (`-np 1`); CLI and web must not compete |
| Bind to 127.0.0.1; refuse non-loopback without authentication | Security requirement |
| Incident ID must match the existing schema (`INC-` + 3–6 digits) | Changing schemas would alter shared contracts |
| Repeat index per (investigation, mode) | `run_one` seeds from repeat; re-analysis creates `r1`, `r2` … deterministically, never overwrites |

## 5. Items that could change RCA behaviour (none adopted)

* Changing prompts, budget, model, temperature, tools, gate or validator — **not done**.
* Auto-detecting incidents — not part of the evaluated system; not added.
* The web path calls the same `run_one`; the only difference from the experiment is the case source (uploaded
  files) and the output directory.

## 6. Stage plan

M1 shared services + store + renderer + CLI; M2 web/API foundation; M3 uploads and validation; M4 E2b/E3 jobs;
M5 progress and report pages; M6 history and downloads; M7 authentication and security; M8 tests; M9 docs and
startup; M10 review. Real Ollama inference is not used until the dissertation experiment has finished.
