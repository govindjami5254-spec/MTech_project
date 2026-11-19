# LogAgent-RCA — Decision Log

Status values: **Agreed**, **Tentative** (needs verification), **Open**.

## Decisions

| ID | Date | Decision | Rationale | Status |
|---|---|---|---|---|
| D-001 | 2026-11-19 | Investigation source is log files only | Agreed scope | Agreed |
| D-002 | 2026-11-19 | Local inference with Ollama; no mandatory cloud API. FreeLLMAPI rejected for experiments | Reproducibility, RQ3 resource measurement, data privacy | Agreed |
| D-003 | 2026-11-19 | Primary model `qwen3:8b`, sensitivity model `llama3.1:8b` | Tool support confirmed via `ollama show`; fits 16 GB RAM | Tentative — not yet tested on target laptop |
| D-004 | 2026-11-19 | Develop on Linux server, containerise with Docker, then validate on personal laptop; code must support Windows and Linux | User workflow | Agreed |
| D-005 | 2026-11-19 | Proof-of-concept preserved in a project-local repo, branch `poc-preservation`, commit `e7bdd9d` | Keep prior work before redesign; home-directory repo left untouched | Agreed |
| D-006 | 2026-11-19 | Internal implementation name **LogAgent-RCA**; dissertation title unchanged unless supervisor approves | Avoid clash with arXiv 2607.22385 ("AgentRCA"); no clash found on arXiv, PyPI, GitHub | Agreed |
| D-007 | 2026-11-19 | Strong single-pass baseline E2b is the primary comparison; E2a is secondary | Avoid a strawman baseline | Agreed |
| D-008 | 2026-11-19 | Include E2-oracle and E2-matched | Separate evidence discovery from reasoning; control for extra compute | Agreed |
| D-009 | 2026-11-19 | Pre-declared primary test: E3 vs. E2b top-1 on unseen test cases | Faculty requirement for a clean comparison | Agreed |
| D-010 | 2026-11-19 | A null result is acceptable and will be reported as found | Scientific validity | Agreed |
| D-011 | 2026-11-19 | E3 final call gets evidence + investigation trace; E2-oracle gets the same evidence without the trace | Makes E2-oracle a meaningful diagnostic | Agreed |
| D-012 | 2026-11-19 | One shared temperature > 0 for all LLM arms (candidate 0.2) | Required for E2-matched sampling and meaningful repeated runs | Agreed — exact value open |
| D-013 | 2026-11-19 | Ablations A1, A2, A3, A5 mandatory; A4 conditional on the inclusion rule | Keep scope achievable | Agreed |
| D-014 | 2026-11-19 | E1 includes a log-free floor baseline alongside detection and temporal/propagation rules | Honest minimum (lesson from arXiv 2609.27069) | Agreed |
| D-015 | 2026-11-19 | Workflow order: audit → resource discovery → research design → technology selection → architecture approval → module-by-module implementation | Research needs drive technology choice | Agreed |
| D-016 | 2026-11-19 | Final contribution has four elements: controlled comparison, coverage gate, grounding validator, safety evaluation | Focused, defensible contribution | Agreed |
| D-017 | 2026-11-19 | Research gap stays provisional until full texts of cited papers are read and relied-upon claims verified | Abstract-level checks are insufficient | Agreed |
| D-018 | 2026-11-19 | Revised gap framing approved; contributions 3 (validator) and 4 (safety) narrowed; absence claims qualified until manual IEEE/ACM/Scholar searches and remaining full-text reads are done | Full-text review found close prior art (2310.16340, 2606.08590, 2604.15368, 2605.24421) | Agreed |
| D-019 | 2026-11-19 | Synthetic test bed is primary for H1; RCAEval RE3 is the primary public external-validity set, with RE2 log-silent cases and Nezha as secondary | Only synthetic data gives evidence-line and propagation ground truth, strata and independence control | Agreed |
| D-020 | 2026-11-19 | Case is the statistical unit; families (shared templates) are split and used for clustered inference; per-case mean over runs; primary = family-level paired permutation test on top-1 difference; ≥ 90 test cases in ≥ 30 families | Q-012 approval; 2609.27069 checklist; power analysis | Agreed |
| D-021 | 2026-11-19 | Detailed literature notes kept in `docs/literature-review.md`; PDFs kept outside Git | Q-013 approval | Agreed |

## Open questions

| ID | Question | Owner | Needed by |
|---|---|---|---|
| Q-001 | Keep "Ericsson pENM" in the title? Supervisor confirmation that no Ericsson data is used | Student / supervisor | Mid-report review |
| Q-002 | Definition of "Real-Time" (e.g., real-time detection + near-real-time diagnosis) or title change | Student / supervisor | Mid-report review |
| Q-003 | Final submission date and remaining milestones | Student | Before technology selection |
| Q-004 | Does the laptop have a GPU? Is a university GPU available? | Student | Before compute planning |
| Q-005 | Is the dashboard evaluated or demo only? | Student / supervisor | Architecture approval |
| Q-006 | Student-ID inconsistency and supervisor remarks raised by faculty | Student | Mid-report review |
| Q-007 | Exact shared temperature value | Team | After dev-set pilot |
| Q-008 | Which public datasets support log-only root-cause and evidence ground truth | Team | **Answered (D-019):** RCAEval RE3 primary; no public set has evidence labels at scale |
| Q-009 | A4 time box | Team | After E3 works |
| Q-010 | Test-set size and runs per configuration, given compute budget | Team | After Q-003, Q-004 |
| Q-011 | Revised gap framing | Student | **Closed (D-018)** |
| Q-012 | Statistical unit of analysis | Team | **Closed (D-020)** |
| Q-013 | Save literature notes | Student | **Closed (D-021)** |
| Q-014 | Manual Google Scholar / IEEE Xplore / ACM DL searches (automated access blocked) | Student | Before final gap |
| Q-015 | Full-text read of ★ papers | Team / Student | 3 of 6 done (A18–A20). Context-RCA, RCAgentOps, VerifyRCA need manual browser download (CC-BY on IEEE Xplore) |
| Q-016 | Resolve licence conflicts (RCAEval, GAIA, Loghub) and verify OpenStack-RCA-Bench availability | Team | Before data use |
| Q-017 | Compute budget of ~180–250 CPU hours: GPU access or reduced secondary arms | Student | Architecture approval |

## Mid-report review (next week)

Not expected by then: full experiment results. Planned material: research gap and design (this
folder), proof-of-concept status with limitations stated honestly, implementation plan and timeline.
