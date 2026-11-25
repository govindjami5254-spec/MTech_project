# M10 — Final review of the LogAgent-RCA web application and CLI

Branch `feature/logagent-rca-web` (worktree `/home/zjamgov/kiro-web`), based on the frozen commit `c5448ef`
(tag `test-freeze`). Reviewed 2026-11-25 while the frozen test experiment (`results/test-main`) was running.

## Acceptance criteria

| Requirement | Status | Evidence |
|---|---|---|
| Two access methods (CLI, web) over the same backend | Met | `service.AppService` used by `__main__.py` and `web/app.py` |
| No second RCA engine | Met | Both call `runner.run_one`; existing engine modules are not modified (`git diff c5448ef` changes only `__main__.py`, `.gitignore`; all else added) |
| Same model, Ollama, parameters | Met | `configs/app.yaml`; `test_app_config_uses_identical_model_and_research_settings` |
| Same persistence, no separate database | Met | `store.InvestigationStore` (files under `workspace/`) |
| CLI and web produce the same result | Met (scripted LLM) | `test_cli_and_web_produce_identical_reports`, `test_service_result_equals_direct_engine_on_same_bundle` |
| Research CLI unchanged | Met | `test_research_cli_commands_unchanged`; `run --help` / `analyze --help` identical to the frozen tree |
| No writes to `results/test-main`, frozen tree untouched | Met | Work done in a separate worktree and venv; `git diff --quiet c5448ef` in the frozen tree passes |
| No additional Ollama inference | Met | All tests use a scripted LLM; smoke check only queries `/api/version` and `/api/tags` |
| Analyses refused while the experiment runs | Met | `test_analysis_refused_while_experiment_runs`, `test_refused_while_experiment_running` |
| Bound to localhost | Met | Default 127.0.0.1; non-loopback refused without `--auth-file`; TrustedHost check |
| Upload validation, path containment | Met | `test_upload_content_rules`, `test_size_and_count_limits`, `test_path_traversal_filename_is_sanitised_and_contained` |
| CSRF / auth / roles | Met | `test_csrf_header_required`, `test_auth_required_and_roles`, `test_tampered_or_expired_session_rejected` |
| Untrusted log content not rendered as HTML | Met (static checks) | `test_log_content_is_not_rendered_server_side`; app.js uses no HTML-string sinks; CSP forbids inline scripts |
| Progress, report, evidence tracing, history, downloads, re-analysis | Met | `test_upload_analyze_report_evidence_downloads`, `test_reanalysis_creates_new_repeat_and_never_overwrites`, `test_source_lines_trace_evidence_to_original_file` |
| Restart recovery | Met | `test_worker_recovery_after_restart` |
| Not only a mockup | Met | Real server smoke check (`scripts/smoke_web.py`): all pages 200, health reports Ollama and model |

## Test results

* Full suite in the worktree: **231 passed** (166 pre-existing research tests + 65 application tests).
* Real server smoke check: all pages HTTP 200; `/api/health` ok (Ollama reachable, `qwen3:8b` installed,
  `experiment_running: true`); POST without anti-CSRF header → 403; foreign Host header → 400.

## Limitations

* **No end-to-end test with real inference yet.** Deferred until the research experiment finishes; then run
  `diagnose` on one development case in E2b and E3 mode and check the report in the browser.
* JavaScript was not executed (no JS runtime or browser on the server); only static checks of IDs and sinks.
* One worker and one server process; analyses are serialised (Ollama `-np 1`). Several minutes per analysis on CPU.
* Sessions are invalidated on restart; no password reset or user management UI (CLI `add-user` only).
* No delete or retention endpoint; `workspace/` grows until cleaned manually.
* Only the line format `<timestamp> <LEVEL> <component> <message>` is supported.
* The user must name the trigger line; there is no automatic incident detection.
* File lock tested on Linux only. No container image.
* Confidence values are model self-assessments; recommendations are not evaluated.
* Not hardened for exposure beyond localhost (no TLS, rate limiting or audit of logins).

## Recommendation

Keep the branch separate from `logagent-rca` until the experiment and its analysis are finished; then run the
real end-to-end check and decide on merging. The web application is not part of the dissertation's experimental
evidence.
