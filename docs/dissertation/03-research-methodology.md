# Chapter 3 — Research Methodology

> **Draft status (2026-11-25).** Written while the frozen test experiment is running. Contains no test-set
> results. Items marked **[OPEN]** need the student's or supervisor's action; **[CITATION NEEDED]** marks a
> statement whose source has not been verified and must not be submitted as is.
>
> Project sources: `docs/research-design.md` (RD), `docs/preregistration.md` (PR), `docs/decisions.md` (D-xxx,
> Q-xxx), `docs/literature-review.md` (LR, entries A1–A20 and Part B). The frozen experiment is commit
> `c5448ef`, tag `test-freeze`.

## 3.1 Introduction

This chapter describes how the research question is answered: the comparison strategy, the experimental arms,
the construction of the evaluation data, the evidence-budget protocol, the metrics and the statistical
analysis. The design was fixed before any test case was run and is recorded in a pre-registration document
(PR), committed and tagged before the test experiment started.

**Scope note on the title.** The dissertation title refers to "Real-Time Root Cause Diagnosis ... in Ericsson
pENM Deployments". The work is vendor-independent: no Ericsson, employer or production data, documents or
infrastructure are used, and all evaluation data is synthetic (Section 3.6). Measured diagnosis latency is in
the order of minutes per incident on the available CPU-only hardware (Section 3.10), not seconds.
**[OPEN — Q-001, Q-002]** Supervisor clarification is required on (a) retaining "Ericsson pENM" in the title
given the vendor-independent scope, and (b) the intended meaning of "Real-Time" (for example, real-time
incident detection with near-real-time diagnosis) or a title revision.

## 3.2 Research problem

In distributed systems, a single failure produces errors in many components. The component that reports the
incident is frequently a downstream symptom, while the root cause lies several dependency hops away. Large
language models (LLMs) can interpret unstructured logs, but the literature reviewed for this work (LR) shows
two competing designs:

1. **Iterative, tool-using agents** that collect evidence step by step (e.g. RCAgent, arXiv:2310.16340; the
   agent evaluated in the OpenRCA line of work, arXiv:2602.09937, arXiv:2606.27154).
2. **Deterministic evidence pipelines followed by a single LLM call** (e.g. Log-Insight, arXiv:2607.08529;
   EviRCA, arXiv:2609.19825; Loom, arXiv:2609.02649).

Failure studies report that agents explore incompletely and misinterpret data, and that prompt changes alone
do not remove these failures (arXiv:2602.09937). The closest controlled comparison found (arXiv:2601.22208)
reports diminishing or negative returns from agentic workflows with locally run open models. Among the works
reviewed, none compares the two designs with the same evidence and a matched evidence budget, on log-only
input, while enforcing exploration coverage and claim grounding in code (RD §3; LR Part A).

**[OPEN — Q-014, Q-015]** This statement of the gap is qualified to the reviewed works. Manual searches of
Google Scholar, IEEE Xplore and ACM Digital Library (automated access was blocked), and full-text reading of
three IEEE papers (Context-RCA, DOI 10.1109/jcc72984.2026.00052; RCAgentOps, DOI
10.1109/aiotc71250.2026.11689122; VerifyRCA, DOI 10.1109/icetis70504.2026.11633469), are outstanding. Context-RCA
may overlap the coverage-gate mechanism and must be read before the gap is finalised (LR Part B, Part C).

## 3.3 Research question

> **RQ.** Does iterative evidence collection improve log-based root-cause diagnosis over a strong single-pass
> LLM when both have the same unique-evidence token budget?

The question was narrowed from the original proposal (D-022) so that "the same budget" has an operational
meaning (Section 3.8) and the study is achievable on CPU-only hardware before the submission deadline.

## 3.4 Objectives and hypotheses

Objectives:

1. Implement a controlled, read-only, log-based RCA framework with interchangeable diagnosis strategies that
   share ingestion, evidence accounting, output schema and validation.
2. Construct labelled evaluation data with root-cause and supporting-evidence ground truth, separated from
   all data visible to the diagnosis strategies, with independent development and test families.
3. Compare iterative and single-pass diagnosis under a strict, identical evidence-token budget.
4. Measure the contribution of two controller-level mechanisms: the coverage gate and the grounding
   validator.
5. Measure the computational cost of each strategy (tokens, latency, CPU, memory).

Pre-registered hypotheses (PR §1):

| ID | Hypothesis | Measure |
|---|---|---|
| H1 (primary) | E3 differs from E2b in diagnostic correctness | `correct`, E3 − E2b |
| H2 | E3 has a lower unsupported-claim rate and a higher grounded-diagnosis rate than E2b | raw unsupported-claim rate; `grounded` |
| H3 | E3's additional cost is measurable and bounded | processed tokens, latency, CPU, memory |
| H4 | Removing the coverage gate (A2) or the validator (A3) changes E3's outcome | E3 − A2, E3 − A3 |

A null result is treated as a valid outcome (D-010). Because the test set is small (Section 3.9), the study is
**exploratory**: effects are reported with confidence intervals and no claim of statistical significance is made
(D-024).

**Scope reductions (D-024).** The original design (RD §5–§7) also planned a naive single-pass arm, an oracle-
evidence arm, a compute-matched arm, further ablations, public-dataset evaluation and an LLM-based adversarial
safety evaluation. These were deferred because of the deadline and CPU-only hardware. Safety controls are
implemented and unit-tested (Chapter 4), but **[OPEN]** no adversarial prompt-injection experiment with the LLM is
part of the frozen test experiment; the safety contribution must be described accordingly.

## 3.5 Research design and comparison strategy

The study is a within-case controlled comparison. Every arm diagnoses every test case from the same case bundle
(log files and an incident description). The arms differ only in how evidence is selected and presented.
Everything else is held constant (PR §2, §4):

* the same model, quantisation, context length, maximum output length and temperature;
* the same system prompt, final instruction and JSON output schema for both LLM strategies;
* the same strict unique-evidence budget B and the same token accounting;
* the same post-hoc grounding validator and the same scoring rules.

Processed prompt tokens (including repeated conversation history) are *not* equalised: the iterative arm is
expected to process more tokens, and this is measured as cost rather than controlled (D-023).

### 3.5.1 Experimental arms

| Arm | Definition | Runs per case |
|---|---|---|
| **E1** | Rule-based RCA. From the incident component, follow the most frequently mentioned other component in its WARN-or-worse lines; repeat until no further dependency is named. If the final component logs no ERROR/FATAL lines itself, report insufficient evidence. Rules were written using development data only | 1 (deterministic) |
| **E1f** | Log-free floor. Names the incident's own component and cites only the trigger line. It measures the score obtainable without reading the logs (motivated by arXiv:2609.27069) | 1 (deterministic) |
| **E2b** | Strong single-pass LLM. Deterministic clustering of log lines into message templates, ranking, packing under B, then one final LLM call (design inspired by Log-Insight, arXiv:2607.08529) | 2 |
| **E3** | Iterative agentic RCA. The model calls read-only tools to collect evidence under B; the coverage gate is enabled; the final answer is requested in the same conversation | 2 |
| **A2** | E3 with the coverage gate disabled | 2 |
| **A3** | E3's raw (unvalidated) report scored directly; derived from E3 runs, no additional model call | derived |

The grounding validator is applied to the raw report of every arm; arms are scored on the validated report,
except A3. Comparing E3 with A2 isolates the coverage gate; comparing E3 with A3 isolates the validator.

## 3.6 Evaluation data

### 3.6.1 Rationale for synthetic data

Public datasets were reviewed for log-only RCA (RD §8.1). None of those checked provides supporting-evidence
labels at useful scale; several record the fault mainly in metrics or traces, so logs alone are insufficient;
some have licence conflicts or label leakage. A synthetic test bed was therefore chosen as the primary
evaluation data (D-019), because it alone provides, for every case, the root-cause component, key evidence
lines, the propagation path and a controlled difficulty stratum. Public datasets remain future work
**[OPEN — Q-016]**.

### 3.6.2 Generator and case families

The generator (`logagent_rca/synth/`, version 2.0.0) produces multi-component logs for a request path. A
**family** is a scenario template, the combination of:

* a **topology** (an entry service and its dependency graph, plus unrelated components),
* a **log vocabulary** (message phrasing, timestamp format, level spelling),
* a **difficulty stratum**,
* one or two **faults** and their target components.

Cases within a family differ only by seeded variation: date, fault time (300 ± 30 s into a 600 s window),
traffic timing, request identifiers and volumes. Each case contains steady INFO traffic for every component
(one line every 6–14 s), rare benign warnings (probability 0.03 per line), the fault's own log lines on the
root-cause component, and a cascade of dependency errors propagating to the entry service, which returns 5xx
errors to clients. The first entry-service 5xx line is the incident trigger.

Difficulty strata (RD §8.3):

| Stratum | Construction | Test families |
|---|---|---|
| easy | root cause one hop from the entry service | 3 |
| multi_hop | root cause three or more hops away | 4 |
| distractor | unrelated warnings/errors on off-path components appear *before* the root cause; failure-path components stay quiet before the fault | 4 |
| over_budget | high-volume repeated errors and unrelated warning floods; WARN-or-worse volume far above B | 4 |
| concurrent | two independent faults in different branches within ± 40 s | 2 |
| insufficient | the faulty component logs nothing abnormal; callers only report timeouts; the correct answer is abstention | 3 |

### 3.6.3 Ground truth and data separation

For each case the generator writes, separately:

* an agent-visible **case bundle**: `incident.json` (case id, incident description, time, trigger line,
  file list) and one log file per component;
* a **ground-truth file** in a disjoint directory: root-cause component(s), fault type, key evidence lines,
  relevant evidence lines (root-cause and propagation lines), propagation path, stratum and family id.

Separation is enforced in code (Chapter 4): the incident schema rejects any unknown field, so truth fields cannot
be written into a bundle; the configuration rejects truth and case directories that overlap; ingestion reads only
the listed files inside the case directory; case identifiers are opaque (`test-c007`) and assigned by a seeded
shuffle; only the scoring module reads ground truth. Automated tests check that no truth field, family id or
fault name appears in any bundle (`tests/test_m3_synthetic.py`).

### 3.6.4 Development and unseen test split

| Split | Families | Cases | Topologies | Vocabularies |
|---|---|---|---|---|
| Development | 6 (one per stratum) | 18 | `dev-shop`, `dev-ledger` | `dv-java`, `dv-go` |
| Test | 20 | 60 (3 per family) | `t-media`, `t-travel`, `t-iot`, `t-bank` | `tv-python`, `tv-node`, `tv-rust` |

Development and test templates were written in separate modules and share no topology, component name, message
phrasing or vocabulary (checked by test). The test vocabularies include timestamp formats (`+05:30` offsets,
comma milliseconds) and level spellings (`info`, `ERR`, `CRITICAL`) not used in development. The test split was
frozen at commit `a4a6c25`, before any arm that uses an LLM was implemented; a regeneration test reproduces both
splits byte for byte, and the runner verifies every file against the frozen `SHA256SUMS` before each run
(test digest `7b39d343…72ad`). All development work (rule writing for E1, prompt development, the pilot and the
choice of B) used development data only.

Measured volumes (test split, exact tokens of canonical evidence lines; D-029): every case contains roughly
27k–83k tokens of logs; median WARN-or-worse volume is 1.2k–2.4k tokens in the non-over-budget strata and
47k–64k in over-budget cases.

**Limitation.** Generated error messages frequently name the failing dependency. E1 exploits this and scored
18/18 on development data (Q-020); it may be near ceiling on test data. This is a property of the synthetic
data and is reported as a threat to validity.

## 3.7 Development pilot

A development pilot (18 cases, all arms, one run each, provisional B = 3,000) was run to verify the pipeline,
measure runtime and calibrate the run plan (`results/dev-pilot`, tag `pilot-dev-start`). Its outputs were used
only for runtime planning and operational checks; they are not evidence for the hypotheses and are not reported
as results. B was not chosen from pilot accuracy (Section 3.8).

## 3.8 Evidence budget

### 3.8.1 Definition

B is a strict cap on the **unique evidence tokens** presented to the model for one case (D-023, D-028).
Each evidence item is rendered in a single canonical line

```
[E<n>] <timestamp> <SEVERITY> <component> (<source>:<line>) <message>
```

and charged the exact number of tokens of that line plus its newline, counted with the model's own tokenizer.
An item is identified by its source file and line number, and is charged once, when first presented; showing
it again is free against B but recorded as repeated exposure. Prompt text, framing tags and the chat template are
overhead and are not charged. The incident trigger is charged in every arm. An item is admitted only if the used
budget plus its cost does not exceed B. Total processed prompt tokens are recorded separately and are not equal
across arms.

A calibration against Ollama's reported prompt-token counts found a constant difference of 16 tokens (user
message only) or 21 tokens (with a system message), attributable to the chat template, with no size-dependent
drift for 1–60 evidence items (RD §6; `results/calibration/`).

### 3.8.2 Selection rule and rationale for B = 900

Because the research question concerns evidence *selection* under a budget, B must bind for a strong single
pass in a meaningful share of cases. At the provisional B = 3,000, one instance of every distinct WARN-or-worse
message pattern fitted within B in all 18 development cases, so the budget would not have constrained E2b.

Five candidate rules were evaluated on development data only (PR §3; `results/dev-pilot/analysis/b-selection-dev-only.txt`):

| Rule | B | Dev cases where all WARN+ lines exceed B | Dev cases where one instance per WARN+ pattern exceeds B |
|---|---|---|---|
| R1 fixed (provisional) | 3,000 | 3/18 | 0/18 |
| R2 median of all WARN+ lines | 1,391 | 9/18 | 2/18 |
| R3 25th percentile of all WARN+ lines | 1,194 | 13/18 | 3/18 |
| **R4 median of one-instance-per-pattern WARN+ (approved)** | **900** | **16/18** | **9/18** |
| R5 largest B fitting the context | 6,242 | 3/18 | 0/18 |

The approved rule R4 sets B to the development median of the tokens needed to show one instance of each distinct
(component, message template) WARN-or-worse pattern within the analysis window, rounded down to a multiple of 100:
904 → **B = 900** (D-034). The rule uses data volumes only; no accuracy measurement from the pilot or the test set
was an input. Root-cause lines require a median of 145 and a maximum of 276 tokens on development data, so they fit
under B. An operational check at B = 900 on six development cases (30 runs, all successful) confirmed strict budget
enforcement and valid evidence references; it also showed that E3 exhausts B early, so the coverage gate is often
inactive at this budget (D-035). Results apply to this B and are not generalised to other budgets.

## 3.9 Evaluation metrics and statistical analysis

### 3.9.1 Metrics (PR §7)

* **correct** (primary). For expected-abstention cases: the report abstains. For all other cases: the report does
  not abstain and its top-ranked component is a true root cause.
* **top3**: a true root cause is among the first three hypotheses (abstention cases: as `correct`).
* **grounded**: correct, and the top hypothesis cites at least one key-evidence line.
* **evidence precision**: share of cited lines that are relevant (root-cause or propagation lines).
* **evidence coverage**: share of key-evidence lines that are cited.
* **unsupported-claim rate**: share of claims in the raw report not supported by their cited evidence, as judged
  by the validator; **fabricated IDs**: cited evidence identifiers that were never presented.
* **cost**: unique evidence tokens, repeated exposures, processed prompt and output tokens, LLM calls, tool calls,
  coverage-gate rounds, invalid-output retries, truncated output fields, wall-clock and LLM time, CPU seconds,
  mean CPU utilisation, and memory of the Ollama process tree (USS, PSS and RSS) with host memory as context.

### 3.9.2 Statistical analysis (PR §8; D-020)

* **Unit of analysis.** The case. A case's score is the mean over its runs; repeated runs measure within-case
  variability and are never counted as independent cases, following the recommendation in arXiv:2609.27069.
* **Clustering.** Cases from the same family share a template and are not independent; inference is therefore
  performed at family level.
* **Primary analysis.** The mean per-case difference E3 − E2b in `correct`, with a 95% cluster-bootstrap
  confidence interval (10,000 resamples: families with replacement, then cases within each family) and a
  two-sided family-level sign-flip permutation test (exact enumeration of 2^20 sign patterns)
  [CITATION NEEDED — cluster bootstrap and permutation test references].
* **Sensitivity analysis.** An exact McNemar test on per-case majority outcomes (with two runs, a case counts as
  correct if at least one run is correct; the rule is identical for both arms) [CITATION NEEDED — McNemar (1947)].
* **Secondary comparisons.** E3 − E1, E2b − E1, E3 − A2, E3 − A3, unsupported-claim rate, grounded diagnosis and
  evidence coverage, with Holm-adjusted p-values [CITATION NEEDED — Holm (1979)]; results also reported per stratum.
* **Power.** With 60 cases, an exact McNemar test has an estimated power of about 0.58 to detect a 15-point
  difference, before accounting for clustering (RD §11). Effects are therefore interpreted from their magnitude and
  confidence intervals; p-values are descriptive.

A study by Hussain and Farrukh (Research Square preprint, DOI 10.21203/rs.3.rs-11401166/v1) used a similar
cluster-bootstrap and sign-flip procedure for single-call RCA (LR A18); it is cited as methodological precedent.

## 3.10 Experimental procedure and reproducibility

1. **Freeze.** The configuration, pre-registration and code were committed and tagged `test-freeze` (commit
   `c5448ef`) before the first test run. Any later change is a reported deviation.
2. **Integrity checks.** Before running, the runner verifies every dataset file against the frozen checksums and
   refuses to run the test split from a working tree with uncommitted tracked changes.
3. **Execution.** 480 runs: E1 60, E1f 60, E2b 120, E3 120, A2 120. Order is repeat-major (all cases for repeat 0,
   then repeat 1), so an interrupted experiment remains balanced across cases. Seeds are deterministic: run seed
   = 1000 + repeat; per-call seeds are derived from it (PR §4).
4. **Fixed settings.** `qwen3:8b` (Q4_K_M) via Ollama 0.40.16, temperature 0.2, no "thinking" mode, context 8,192
   tokens, maximum 450 output tokens per call, Qwen3 tokenizer with verified SHA-256.
5. **Recording.** Each run stores a validated run record (inputs' provenance, raw and validated reports, evidence,
   tool calls, metrics), an audit log and, for LLM arms, the full message transcript. Records are written
   atomically; completed runs are skipped on resumption.
6. **Failure handling.** No case or run is excluded after the fact. Invalid output receives one in-call retry; an
   infrastructure error triggers up to two whole-run retries; any run still failing is scored as incorrect and
   reported.
7. **Hardware and latency.** All inference runs on a shared four-core CPU server without a GPU, with load from
   other users. Development measurements give per-run times of minutes, for example a median of 462 s for E2b and
   750 s for E3 in the operational check at B = 900, and are hardware- and load-specific. The estimated duration
   of the test experiment is about 56 hours. **No claim is made that diagnosis completes in seconds.**
8. **Memory.** After loading, the model process uses about 6.8 GB (unique memory). Ollama's default host prompt
   cache can add up to 8 GiB; about 15 GB was observed during the pilot (D-032). Fitting a 16 GB laptop is not
   claimed and has not been measured.

## 3.11 Ethical considerations and safety boundaries

* **Data.** Only synthetic logs are used. No personal, customer, employer or production data is processed. The
  generator contains a deliberately fake credential and e-mail address to test redaction.
* **Local inference.** The model runs locally through Ollama; no log content is sent to an external service. The
  model weights and tokenizer were obtained from public sources under the licences stated by their publishers
  **[OPEN — confirm and cite the Qwen3 model licence from the official model card]**.
* **Read-only operation.** The system cannot execute commands, modify files, call external networks or perform
  remediation. It can only read the case's logs through three read-only query tools validated by code.
  Recommendations are advisory text for a human operator.
* **Untrusted input.** Log text is treated as untrusted data: it is sanitised, wrapped in delimiters, scanned for
  instruction-like content, and lines flagged as possible prompt injection can never support a diagnosis claim.
* **Transparency.** Every model input and output, tool call and refusal is logged; the pre-registration and all
  run records are retained.
* **Limits of the safety claim.** These controls are implemented and unit-tested, but their effectiveness against
  adversarial log content has not been evaluated with the LLM in this study (Section 3.4).

## 3.12 Threats to validity (summary)

* Synthetic data authored by the researcher; templates for the test split were written separately and frozen,
  but realism is not established.
* Synthetic messages name failing dependencies, favouring rule-based E1.
* Small sample (60 cases, 20 families); exploratory inference only.
* Single model (8B, quantised, local); results may not transfer to other models.
* Single shared CPU host; latency and memory depend on load and Ollama configuration.
* The lexical grounding validator has not been checked against human judgement **[OPEN]**.
* Results hold for B = 900 only.

## 3.13 Summary

The methodology compares iterative and single-pass LLM diagnosis under an identical, strictly enforced evidence
budget, with a rule-based baseline, a log-free floor and two ablations, on frozen synthetic data with separated
ground truth, using family-level exploratory statistics fixed before the test experiment.

---

### Open items for this chapter

| Ref | Item |
|---|---|
| Q-001 | Supervisor: keep "Ericsson pENM" in the title? |
| Q-002 | Supervisor: definition of "Real-Time" or title revision |
| Q-006 | Student-ID inconsistency raised by the faculty |
| Q-014 | Manual Scholar / IEEE Xplore / ACM DL searches |
| Q-015 | Full text of Context-RCA, RCAgentOps, VerifyRCA |
| Q-016 | Public datasets and licence conflicts (future work) |
| — | Safety: no LLM-based adversarial evaluation in the frozen experiment; describe contribution 4 accordingly |
| — | Validator not yet checked against manual labels |
| — | Citations needed: cluster bootstrap, permutation test, McNemar, Holm, Qwen3 model card/report, Ollama |
