# LogAgent-RCA — Pre-registration of the test experiment

**Status: FROZEN (approved 2026-11-25).** This file and `configs/test.yaml` are committed together and tagged
`test-freeze`; the tag commit is cited in the dissertation. No test case was run before the tag. Any later change
is reported as a deviation.

## 1. Research question and hypotheses

**RQ.** Does iterative evidence collection improve log-based root-cause diagnosis over a strong
single-pass LLM when both have the same unique-evidence token budget B?

| ID | Hypothesis | Measure |
|---|---|---|
| H1 (primary) | E3 differs from E2b in diagnostic correctness | `correct`, E3 − E2b |
| H2 | E3 has a lower unsupported-claim rate and higher grounded-diagnosis rate than E2b | raw unsupported-claim rate; `grounded` |
| H3 | E3's additional cost (processed tokens, latency, CPU) is measurable and bounded | cost metrics |
| H4 | Removing the coverage gate (A2) or the validator (A3) changes E3's outcome | E3 − A2, E3 − A3 |

A null result is a valid outcome. The design is **exploratory** (60 cases, 20 families): effects are
reported with confidence intervals; **no claim of statistical significance is made** (D-024).

## 2. Arms

| Arm | Definition | Runs per case |
|---|---|---|
| E1 | Rule-based: follow the most-mentioned dependency in WARN+ lines from the incident component; abstain if the terminal component logs no ERROR/FATAL. Rules written on development data only | 1 (deterministic) |
| E1f | Log-free floor: names the incident component; cites only the trigger | 1 (deterministic) |
| E2b | Strong single pass: template clustering, severity/first-occurrence ranking, packing under B, one final call | 2 |
| E3 | Iterative: read-only tools (`error_timeline`, `search_logs`, `get_context`) under B, coverage gate on, grounding validator applied | 2 |
| A2 | E3 with the coverage gate disabled | 2 |
| A3 | E3's raw report scored before validation (no extra model run) | derived |

E2b and E3 share the system prompt, final instruction and JSON output schema; E3's final call is appended
to its own conversation, so it also sees its investigation trace.

## 3. Evidence-token budget B

**Definition (D-023, D-028; unchanged).** B caps the unique evidence tokens presented to the model per case.
Each canonical evidence line `[E<n>] <ts> <SEV> <component> (<source>:<line>) <message>` plus newline is
charged once per stable uid, counted with the Qwen3 tokenizer; repeats are free but recorded; prompts and
framing are overhead. The incident trigger is charged in every arm.

**Selection rule (approved, R4).** B = 50th percentile, over the 18 development cases, of the tokens needed to
show one instance of every distinct (component, message-template) WARN-or-worse pattern in the analysis
window, rounded down to a multiple of 100. Development value 904 → **B = 900**.

Rationale: the RQ concerns evidence selection under a *binding* budget. Computed from development data volumes
only; no accuracy result (pilot or test) is an input. The pilot ran at the provisional B = 3,000 and is not used
to choose B.

| Rule (development data only) | B | Dev cases with raw WARN+ > B | Dev cases with deduplicated WARN+ > B |
|---|---|---|---|
| R1 fixed 3,000 (provisional) | 3,000 | 3/18 | 0/18 |
| R2 P50 of raw WARN+ | 1,391 | 9/18 | 2/18 |
| R3 P25 of raw WARN+ | 1,194 | 13/18 | 3/18 |
| **R4 P50 of deduplicated WARN+ (approved)** | **900** | **16/18** | **9/18** |
| R5 maximum fitting the context | 6,242 | 3/18 | 0/18 |

Key evidence (root-cause lines) needs a median of 145 tokens on development data (max 276), so it fits under
every candidate.

**Operational check at B = 900 (development only; `results/dev-opcheck-b900`).** 6 dev cases (first case of each
family) × E1, E1f, E2b, E3, A2, one run each: 30/30 runs ok; strict budget held in every run (max 900); every
cited ID in validated reports exists in the run's evidence; 0 fabricated IDs, 0 truncations, 0 blocked calls; 1
E2b invalid-output retry (succeeded); all memory/CPU fields recorded. Observed budget behaviour: E2b packs to
~860–890 tokens; E3 exhausts B early (10 tool results reported "budget exhausted"), so the coverage gate was skipped
6 times for lack of remaining budget and fired in 1 round. This is the specified behaviour, not an implementation
fault; it means A2 and E3 may differ little at this B. Accuracy was not examined for this check.

## 4. Fixed model and prompt configuration

| Item | Value |
|---|---|
| Model | `qwen3:8b` via Ollama 0.40.16, Q4_K_M, 8.2B; weights blob SHA-256 `a3de86cd1c132c822487ededd47a324c50491393e6565cd14bafa40d0b8e686f`; manifest digest `b3d9ba7c899cfd11…` |
| Sampling | temperature 0.2 (all LLM arms), `think: false`, `num_ctx` 8,192, `num_predict` 450 |
| Seeds | run seed = 1000 + repeat (repeat 0, 1). E2b final call: seed; retry: seed+1. E3 step k: seed+k; E3/A2 final: seed+100 (+1 on retry) |
| Agent limits | max 6 steps, min 2 tool calls, ≤ 3 tool calls per turn, coverage gate ≤ 2 rounds (+2 steps each), 1,200 s per run, 3 blocked calls |
| Lookback | 600 s before the incident (+120 s after) |
| Output limits | text ≤ 160 chars, ≤ 3 hypotheses, ≤ 3 claims, ≤ 4 IDs per claim, ≤ 2 gaps / recommendations; over-long fields truncated identically for all arms and counted (`normalised_fields`) |
| Validator | min 2 content-word overlap (exact or ≥ 5-char shared prefix); injection-flagged lines never support |
| Prompt SHA-256 | system `3159f3f0…3478`; final instruction `9a586359…a73e`; output schema `da8e09ab…3d228`; E3 investigate template `4fece18f…4cd2` |
| Tokenizer | Qwen3-8B `tokenizer.json` SHA-256 `aeb13307…dae4`, `tokenizers` 0.23.3 |

## 5. Data and code

| Item | Value |
|---|---|
| Test split | 60 cases, 20 families × 3; frozen at commit `a4a6c25`; `SHA256SUMS` digest `7b39d3430562fa99cd03a45ad085ae73b601274c3352abbfbe098da1a6fc72ad`; verified file-by-file before every run |
| Dev split (not used in the test) | 18 cases; `SHA256SUMS` digest `7aaf93223775309a780a8b73ddccef5ffdbc8c10a617ae0eeec2190161e1a8e1` |
| Code | commit `a4e2666` + this freeze commit; the runner refuses test runs from a dirty working tree |
| Config | `configs/test.yaml`; `config_hash` `f084f650236305957f9116e615ede9c0cb648ddd97d3aa12302849eddff23ca1` |

## 6. Run plan

480 runs: E1 60, E1f 60, E2b 120, E3 120, A2 120. Repeat-major order (all of repeat 0, then repeat 1), so an
interrupted run remains balanced across cases. Resume with the same command; completed records are skipped.

## 7. Metrics and scoring (scorer is the only reader of ground truth)

* `correct` (primary): expected-abstention cases → correct iff the report abstains; other cases → correct iff it
  does not abstain and its top-ranked cause is a true root cause.
* `top3`, `grounded` (correct and the top hypothesis cites ≥ 1 key-evidence line), evidence precision
  (cited ∩ relevant / cited), evidence coverage (cited ∩ key / key), raw unsupported-claim rate, fabricated IDs.
* Cost: unique evidence tokens, repeated exposures, processed prompt and output tokens, LLM calls, tool calls,
  gate rounds, parse failures, truncated fields, wall and LLM seconds, CPU seconds, mean CPU %, peak USS/PSS/RSS
  of the Ollama process tree, host memory used (context only).
* Arms are scored on validated reports; A3 on E3's raw report.

## 8. Statistical analysis (D-020)

* Unit of analysis: the case. Per-case score = mean over its runs; runs are never treated as independent cases.
* Primary: mean per-case difference E3 − E2b in `correct`; 95% cluster-bootstrap CI (10,000 resamples of
  families, then cases within families); two-sided family-level sign-flip permutation p (exact, 2^20).
* Sensitivity: exact McNemar on per-case majority outcomes (≥ 1 of 2 runs correct counts as correct; ties
  therefore favour neither arm because the same rule applies to both).
* Secondary comparisons (E3 − E1, E2b − E1, E3 − A2, E3 − A3, H2 metrics, evidence coverage): same procedure,
  Holm-adjusted p. Results also reported per stratum (descriptive only).
* Reported as effect sizes with CIs; p-values are descriptive.

## 9. Exclusions and failure handling

* No case or run is excluded after the fact.
* Invalid model output: one in-call retry with the shared correction message; if still invalid, the run is
  `failed` and scored incorrect.
* Ollama/infrastructure errors: the runner retries the whole run up to 2 more times; if still failing, `failed`
  or `aborted`, scored incorrect, and reported.
* Any manual restart resumes the same command; records are never edited or deleted.

## 10. Runtime, hardware and validity caveats

* Shared 4-core CPU server (other users' load 1–13); latency is hardware- and load-specific.
* Pilot means per run: E2b ~9 min, E3 ~12 min, A2 ~7 min → estimated **~56 h** for this plan (range wider under
  load). No claim is made that the system meets a few-minute runtime target.
* Memory: the model process uses ~6.8 GB after loading (USS); Ollama's default host prompt cache can add up to
  8 GiB (~15 GB observed in the pilot; 10.4–10.9 GB in the operational check, host 28.3 of 33.4 GB in use incl.
  other users). Fitting a 16 GB laptop is **not** claimed and must be measured there.
* E1 may be near ceiling because the synthetic messages name failing dependencies (Q-020).
* B is chosen by a volume rule; results hold for that B and are not generalised to other budgets.
