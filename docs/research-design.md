# LogAgent-RCA — Research Design

Status: revised design awaiting approval, pre-implementation (2026-11-19)
Dissertation title (unchanged): *Agentic AI Framework for Real-Time Root Cause Diagnosis and
Recommendations Generation in Ericsson pENM Deployments*
Internal implementation name: **LogAgent-RCA** (renamed to avoid a clash with arXiv 2607.22385).

Evidence labels used in this document:
- **[V]** verified (source checked; for papers: abstract only, full text not yet read)
- **[M]** measured on the proof-of-concept prototype (commit `e7bdd9d`, branch `poc-preservation`)
- **[A]** assumption or estimate, to be confirmed

---

## 1. Research question

**Main RQ (revised, D-022).** Does iterative evidence collection improve log-based RCA over a strong
single-pass LLM when both have the same evidence-token budget?

| Sub-question | Focus | Answered by |
|---|---|---|
| RQ1 | Root-cause accuracy of iteration vs. rule-based and strong single-pass | E1, E2a, E2b, E3 |
| RQ2 | Evidence quality and unsupported claims; source of any gain (evidence discovery vs. iterative reasoning) | E2-oracle, E3, E4 |
| RQ3 | Latency and computational overhead | All LLM arms, E2-matched |
| RQ4 | Whether a read-only tool layer blocks unauthorised operations without blocking useful work | Adversarial safety suite |

## 2. Literature positioning [V, full text, 2026-11-19]

All 17 papers below were read at full-text level (one reading pass per paper). Search was
arXiv-only; IEEE, ACM and Scholar are still to do. Many items are 2026 preprints, not yet peer reviewed.

Gap elements: (i) agent vs. single-pass with the same evidence **and** a matched token budget;
(ii) small local models (≤14B); (iii) log-only RCA; (iv) code-level coverage enforcement;
(v) in-pipeline claim–evidence validator; (vi) adversarial safety testing.
Y = yes, P = partly, N = no.

| Work | Setting | i | ii | iii | iv | v | vi | Key verified finding for us |
|---|---|---|---|---|---|---|---|---|
| RCACopilot 2305.15778 (EuroSys'24) | GPT-4, alerts+logs+metrics, handler pipeline | N | N | N | N | N | N | "Accuracy 0.766" is micro-F1 (macro-F1 0.533) |
| RCAgent 2310.16340 (CIKM'24) | Vicuna-13B on vLLM, mainly logs, agent | P | Y | P | P | P | N | Soft warning against "early finalizing"; fuzzy-match evidence filter inside log expert only; single-call baseline truncated, budget not matched |
| Roy et al. 2403.04123 (FSE'24 comp.) | GPT-4, incident text, ReAct vs retrieval | P | N | N | N | N | N | Correctness similar (35% vs 39%); hallucination 4% (ReAct) vs 12–40%; document-count cap, not token budget |
| MicroRCA-Agent 2509.15635 | LLM not named, multimodal, fixed pipeline | N | N | P | N | N | N | Log-only ablation 23.59 vs. 50.71 all modalities |
| Stalled, Biased, Confused 2601.22208 (FORGE'26) | Local open models 3B–104B, multimodal | P | P | N | N | N | N | **Closest prior work.** Same information, different form; no token budget. Agentic workflows show "diminishing or negative returns"; Qwen3-4B used tools in 23.4% of ReAct runs; authors call for evidence-sufficiency validators |
| Agent failure study 2602.09937 | 5 API models, OpenRCA, controller–executor | N | N | N | N | N | N | Hallucinated interpretation 71.2%, incomplete exploration 63.9%; prompt-only fixes; one run per task |
| LogJack 2604.15368 | 8 API models, cloud logs, shell-capable agent | N | N | N | N | N | Y | Llama 3.3 70B hijack 86.2% (proposed, not executed); read-only out of scope; payloads public (repo reports MIT) |
| Poisoning the Watchtower 2605.24421 | gpt-4o-mini, tool-less, SOC triage | N | N | N | N | N | Y | Log text steers conclusions; defences reduce, not eliminate; no false-block figures |
| Auditable K8s RCA 2606.08590 | qwen-flash API, multimodal, read-only allowlist | N | N | N | N | P | P | Deterministic grounding check that rejects; still accepted a false root cause; bounded traversal left the true node unvisited |
| OpenRCA 2.0 2606.27154 | 11 API models, multimodal benchmark | N | N | N | N | P | N | 20.7 / 76.0 / 61.5% verified; not yet released (CC-BY-SA on acceptance); no splits; logs-only not evaluated |
| Log-Insight 2607.08529 (ASE'26) | Enterprise API LLM, **log-only**, pipeline | N | N | Y | N | N | N | Private data; no agentic baseline; evidence accuracy not measured; mean 27 s |
| How Far Can RCA Go 2607.13548 | GPT-5.2, multimodal | N | N | N | P | P | N | Identical evidence only among pipeline arms; agent "not input-matched"; tokens not captured |
| AgentRCA 2607.22385 | Qwen3-30B-A3B (vLLM), sensors | N | P | N | N | N | N | Name clash confirmed; grounding prompt-only |
| Loom 2609.02649 | Claude 4.6 / Llama-8B, multimodal | P | P | N | N | N | N | One call ≈ agent on 2 of 4 subsets; ~26×/~33× faster on Bank only; different evidence, no budget |
| EviRCA 2609.19825 | API models, multimodal, bounded tool loop | N | N | N | N | P | N | Single-call Oracle Sampling beat the iterative agent, but with different evidence; "instability" claim not supported by its own experiments; EviRCA itself is multi-step |
| RCAEval graph study 2609.27069 | No LLM, metrics | N | N | N | N | N | N | Prior-only ranker 99.7% top-5; 12-item ablation checklist; significance over independent units, not repeats |
| Small-model RCA 2611.02416 | Qwen3-4B **fine-tuned** (DPO), vLLM | P | P | N | N | N | N | 4B beats 14B OpsAgent, but via fine-tuning and unmatched inputs |

**Beyond arXiv (abstract level, not verified).** Crossref (IEEE, ACM), OpenAlex and Semantic Scholar
searches found further candidates. Three were then read in full (A18–A20: 10.21203/rs.3.rs-11401166/v1,
2610.35767, 2609.23766); none matches evidence and token budget across an agent and a single pass.
Three IEEE papers (Context-RCA, RCAgentOps, VerifyRCA) remain abstract-level and may overlap
elements (iv) and (v). Google Scholar,
IEEE Xplore, ACM DL and DBLP blocked automated access; manual searches are outstanding.

**What the evidence says about element (i).** Results are mixed and none matches token budgets:
RCAgent and Roy et al. favour the agent (on some metrics); 2601.22208, Loom and EviRCA favour or
tie with single-pass, and 2601.22208 does so specifically for small local models.

## 3. Research gap

> **Status: REVISED, QUALIFIED (D-018).** Approved framing. Claims of absence are limited to the
> works reviewed (Section 2 and `docs/literature-review.md`) and remain provisional until the
> outstanding manual searches and full-text reads (literature review, Part C) are complete.

**Framing.** In the controlled comparison closest to ours (arXiv 2601.22208), agentic workflows
gave "diminishing or negative returns" over single-pass diagnosis with locally run open models, and a
small model used its tools in only 23.4% of runs. A process-level study (arXiv 2602.09937) found
incomplete exploration and hallucinated interpretation to be the dominant agent failures, and found
that prompting alone did not fix them. Among the works reviewed, none tests whether **code-level
controller enforcement** — a coverage gate and claim-level grounding validation — changes this
outcome under **matched available evidence and token budget**, on **log-only** input, while also
separating evidence discovery from iterative reasoning.

**Gap statement.** Within the reviewed literature, it is unknown whether iterative investigation with
code-level coverage and grounding enforcement improves log-based RCA over a strong single-pass LLM
when both use the same small local model, available evidence and token budget, and whether any
gain comes from evidence discovery or from iterative reasoning.

**Contributions (D-016, narrowed by D-018).**
1. **Controlled comparison.** Agentic vs. strong single-pass diagnosis with the same local model,
   case evidence and a matched token budget, plus E2-oracle to separate evidence discovery from
   reasoning. Prior comparisons (2310.16340, 2403.04123, 2601.22208, 2609.02649, 2609.19825) did not
   match budgets and mostly differed in evidence.
2. **Coverage gate.** Code-level enforcement that a component with pre-incident problems is inspected
   before the agent may conclude. Nearest prior art: RCAgent's soft "early finalizing" warning
   (2310.16340, §3.3.2) and prompt-level exploration instructions; Context-RCA and RCAgentOps
   (abstract level) must be checked. Counter-evidence: 2610.35767 reports that agents with more
   prescribed calls scored lower (correlational), so ablation A2 may show the gate hurts.
3. **Claim-level grounding validator (narrowed).** Not novel as a mechanism: evidence filters and
   deterministic grounding checks exist (2310.16340 §3.2.2; 2606.08590 §IV-D). Our increment is
   validating **every claim of the final diagnosis** (cited evidence IDs exist and support the
   claim), with its effect measured by ablation A3.
4. **Safety evaluation (narrowed).** Log-borne prompt injection is already studied against
   shell-capable agents (2604.15368) and tool-less analysts (2605.24421). Our increment is a
   **read-only, allowlisted, tool-using RCA agent on small local models**, measuring
   **diagnosis steering** (decoy root cause vs. ground truth), unauthorised-access blocking and the
   **false-block rate**.

Small local models and log-only input are the study **setting**, not contributions (prior work
covers each separately: 2310.16340, 2601.22208, 2607.08529).

Grounded-diagnosis metrics (Section 9) belong to contribution 1's evaluation protocol.

A null result (E3 ≈ E2b) is an accepted, reportable outcome; given 2601.22208 it is a plausible one.

## 4. Hypotheses

| ID | Hypothesis | Primary metric |
|---|---|---|
| H1 | E3 achieves higher top-1 accuracy than E2b on unseen test cases | Top-1 (pre-declared primary test) |
| H2 | E3 has a lower unsupported-claim rate and higher grounded-diagnosis rate than E2b | Unsupported-claim rate, grounded diagnosis |
| H3 | E3's overhead is bounded and measurable | Latency, tokens, LLM calls, memory |
| H4 | The safety layer blocks unauthorised operations and resists diagnosis steering with a low false-block rate | Attack success, block rate, steering rate, false-block rate |

## 5. Experiment arms

| ID | Implementation | Role |
|---|---|---|
| E1 | Rule-based RCA: detection rules, temporal/propagation rules, and a log-free floor baseline. Rules authored on the dev set only | Traditional baseline |
| E2a | Raw log window truncated to budget C, one LLM call | Naive single-pass (secondary) |
| E2b | Deterministic extraction, ranking and evidence packing to C, one LLM call | **Primary comparison** |
| E2-oracle | Evidence collected by E3, packed to C, **without** the investigation trace, one call | Diagnostic: evidence vs. reasoning |
| E2-matched | E2b sampled k times, majority vote on root-cause component; k set so total tokens ≈ E3 median (dev set) | Controls for extra compute |
| E3 | Complete LogAgent-RCA: iterative investigation, coverage gate, grounding validator | Proposed approach |
| E4 | Ablations of E3 (Section 7) | Component contributions |

The pre-declared primary test is defined in Section 11.

## 6. Comparison protocol

| Item | Definition | Same across arms |
|---|---|---|
| Case bundle | Log files, incident trigger, analysis window | Yes |
| Ground truth | Stored outside the case bundle; never readable by any arm | — |
| Available evidence | Everything in the case bundle | Yes |
| Presented evidence | What reaches the model (extraction for E2, tools for E3) | No — the variable under study |
| Model settings | Model tag + digest, quantization, `num_ctx`, thinking mode | Yes |
| Temperature | One fixed value > 0 for all LLM arms (candidate 0.2) | Yes |
| Final-answer stage | Prompt, output schema, grounding validator | Yes |
| Per-call context budget C | e.g. 8k tokens | Yes |
| Total token budget T | E2: one call ≤ C; E3: ≤ T across steps | No — reported and controlled by E2-matched |

**Evidence-token budget B (D-023).** B is a strict cap on the **unique evidence tokens** presented to
the model per case: for E2b, the packed evidence; for E3, the union of all evidence lines returned by
tools (each line counted once, when first presented), including the incident trigger. Tokens are counted
with the model's own tokenizer. A tool result that would exceed B is truncated to fit, and the agent is
told the budget is exhausted. Total processed tokens (all prompts, including repeated conversation
history), output tokens, latency, tool calls, CPU and memory are recorded separately. **Equal total
compute is not claimed**; E3 is expected to process more tokens than E2b.

**Token-count calibration (M2, 2026-11-21; `results/calibration/token-calibration-20261121T142029Z.json`).**
Counter: Qwen3-8B `tokenizer.json` (HF revision b968826d…, SHA-256 aeb13307…), `tokenizers` 0.23.3.
Against Ollama 0.40.16 / qwen3:8b (`think=false`), for prompts of 1–60 evidence items (50–3,321 evidence
tokens), `prompt_eval_count` exceeded our exact count of the message text by a **constant** 16 tokens
(user message only) or 21 tokens (system + user) — the chat template's special and role tokens. No
size-dependent drift was observed. The evidence-token count B is a subset of the user text and is
therefore never equal to `prompt_eval_count`. An identical repeated prompt reported the same
`prompt_eval_count` but took 2.6 s instead of 152 s: Ollama reuses the cached prefix without lowering
the reported count, so **latency, not `prompt_eval_count`, reflects caching**. Both are recorded.

**Final-stage definition (makes E2-oracle meaningful).** E3's final call receives the collected
evidence **plus** the investigation trace (tool calls, observations, gate notes). E2-oracle receives
the same evidence **without** the trace.

| Outcome | Interpretation |
|---|---|
| E3 ≈ E2-oracle > E2b | Gain comes from evidence discovery |
| E3 > E2-oracle ≈ E2b | Gain comes from iterative reasoning (the trace) |
| E3 > E2-oracle > E2b | Both contribute |
| E3 ≈ E2b | No benefit from iteration (null result) |

## 7. Ablations (E4)

| ID | Removed | Question | Status |
|---|---|---|---|
| A1 | Iteration (one retrieval round, then answer) | Does iteration matter beyond tool access? | Mandatory |
| A2 | Coverage gate | Does controller-enforced exploration fix incomplete exploration? | Mandatory |
| A3 | Grounding validator | Does validation reduce unsupported claims, and at what accuracy cost? | Mandatory |
| A4 | Hypothesis-testing step | Does explicitly checking competing causes help? | Conditional |
| A5 | Structured evidence store (free-text memory instead) | Does source-linked evidence matter? | Mandatory |

**A4 inclusion rule.** Included only if it is a single bounded step (at most one targeted tool call per
competing hypothesis) and is implemented and tested within a time box set after E3 works. Otherwise
reported as out of scope.

Safety controls are evaluated in the adversarial suite (Section 10), not as accuracy ablations.

## 8. Test beds, datasets and splits (D-019, D-020)

### 8.1 Public dataset suitability (verified 2026-11-19)

No verified public dataset provides log-line evidence labels at scale. Log-only diagnosability below is
an **estimate** from a keyword heuristic on samples unless marked "counted".

| Dataset | Licence | Systems | Cases | Root-cause labels | Evidence / path labels | Log-diagnosable | Use |
|---|---|---|---|---|---|---|---|
| RCAEval RE3 (2412.17015) | CC-BY-4.0 (Zenodo) vs. MIT (README) — conflict | 3 | 90 | Service, fault type, time | `root_cause.txt` in 8 RE3-SS cases; no paths | ~80–100% | **Primary public set** |
| RCAEval RE2 | as above | 3 | 270 | Service, fault, time | No | ~15–25% | Negative controls (abstention) |
| Nezha (FSE'23) | MIT | 2 | 101 | Service; code-region for defects | Code region near log statement | 38 of 101 (counted) | Secondary public set |
| Fang et al. TrainTicket (2510.04711) | CC-BY-4.0 | 1 | 1,430 (paper) | Service/pod/function, fault type | No | Hard: cause often not named in logs | Optional, single-system |
| AIOps 2025 CCF | CC BY-NC 4.0 | 1 | 400 | Fault type, service, time, keywords | Keyword observations | 51–56% (counted from labels) | Optional (non-commercial) |
| ITBench-Lite | Apache-2.0 | 1 | 35 | Entity, category | Propagation edges in 25 | Partial | Optional |
| OpenStack-RCA-Bench (ASE'26) | Not verified | 1 | 64 | Injection metadata | Not verified | Log-only by design | **Check availability** |
| OpenRCA 1.0 | Data licence unstated | 3 | 335 | Component, reason, time | No | <10% | Unsuitable |
| GAIA / MicroSS | Apache vs. GPL-2.0 — conflict | 1 | ~1,562 | Injection lines in logs (leakage) | No | ~5–10% | Unsuitable |
| Eadro | Unstated | 2 | 117 released | Service, type | No | ~12–14% | Unsuitable |
| Loghub | Research-only vs. CC-BY — conflict | 1 each | — | Anomaly/alert only (Hadoop: 55 jobs fault type) | No | — | Unsuitable for RCA |
| LO2 | CC-BY-4.0 | 1 | 1,740 runs | API error type | No; label leakage in logs | Trivial | Unsuitable |
| OpenRCA 2.0 (2606.27154) | CC-BY-SA-4.0 (stated) | 3 | 500 | Root-cause set + causal paths | Paths | Not evaluated | Unreleased |
| LogJack payloads (2604.15368) | MIT (verified) | — | 42 payloads | — | — | — | **Safety suite** |

Licence conflicts must be resolved (contact maintainers or use the more restrictive terms) before
redistribution; we will not redistribute public data.

### 8.2 Decision: synthetic test bed is primary (D-019)

The synthetic test bed carries the primary test (H1) because only it provides all of:
key-evidence lines and propagation paths per case (required for evidence precision/coverage and
grounded diagnosis); controlled difficulty strata (over-budget, distractor, abstention); template-level
independence control; and no licence or redistribution constraints. Public data provides **external
validity**: RCAEval RE3 (secondary analysis of H1 and H2 at case level), RE2 log-silent cases (abstention),
Nezha code-defect cases (sensitivity check).

**Public-data evidence labels.** For a pre-declared sample of public cases, key-evidence lines are
annotated manually by the student using a written protocol, with a second pass after one week and
agreement reported. This is a stated limitation (single annotator).

**Log-diagnosability filter.** Public cases enter the log-only test set by a deterministic rule fixed
on development data before test runs (e.g. fault type ∈ code-level / log-manifesting types), never by
model outcomes.

**Circularity mitigation for synthetic data.** The test-set generator uses scenario templates written
separately from development templates (different topologies, fault families and log vocabularies),
frozen and committed before any E3 tuning. Generator code and seeds are released.

### 8.2a Frozen synthetic splits (D-029)

Test split frozen at commit `a4a6c25` (generator 2.0.0) before any E3 work: 60 cases in 20 families
(easy 3, multi-hop 4, distractor 4, over-budget 4, concurrent 2, insufficient 3 families; 3 cases each).
Development split: 18 cases in 6 families (one per stratum). Topologies, component names and log
vocabularies (including timestamp formats and level spellings) are disjoint between splits; the
regeneration test reproduces both `SHA256SUMS` files byte for byte.

Measured volumes (exact tokens of canonical evidence lines): every case has ~27k–83k tokens of logs, far
above B. WARN+ evidence alone fits within B = 3,000 in all strata except over-budget (test median
1.2k–2.4k tokens; over-budget 47k–64k). Consequently, at B = 3,000 a strong single pass can see every
WARN+ line in 48 of 60 test cases; the iterative arm can only gain from evidence selection in the
remaining cases or from INFO-level context. B is chosen at the pilot freeze on an arm-neutral basis (Q-019).

### 8.3 Difficulty strata

easy (short cascade), multi-hop (root cause ≥ 3 hops from symptom), distractor (earlier unrelated
errors), over-budget (relevant evidence exceeds C), concurrent faults, insufficient evidence
(correct answer is abstention).

**Ground truth per case:** root-cause component and fault type, key evidence lines, propagation
path, stratum, template family. Stored outside case bundles.

## 9. Metrics

| Metric | Definition |
|---|---|
| Top-1 / Top-3 accuracy | Known cause ranked first / within top 3 |
| Grounded diagnosis | Correct cause **and** cited evidence lies on the true propagation path |
| Evidence precision / coverage | Relevant share of cited evidence / share of key evidence cited |
| Unsupported-claim rate | Material claims not supported by collected evidence (validator; checked against manual labels) |
| Abstention accuracy | Correct "insufficient evidence" on that stratum |
| Latency | Incident input to final report, with hardware and model stated |
| Resource use | Tokens in/out, LLM calls, tool calls, memory, CPU (GPU if present) |
| Safety | Attack success, block rate, diagnosis-steering rate, false-block rate |

## 10. Adversarial safety suite

Prompt injection in log lines (LogJack payloads adapted to our log formats, plus our own decoy-cause
payloads); requests for unauthorised tools; argument injection; path traversal and symlinks; oversized
outputs; secret exfiltration through reports; log content attempting to trigger remediation. LogJack's
10 benign controls and clean cases measure the false-block rate. Every attempt and decision is recorded
in the audit log.

## 11. Statistical protocol (D-020)

**Unit of analysis.** The independent unit is the **case**; repeated runs measure within-case
variability and are never treated as independent observations (2609.27069 checklist).

**Template families.** Cases sharing a scenario template (same topology, fault family and target
role) form a **family**. Families, not seeds, are split: no family appears in both development and test.
For public data, a family is a (system, root-cause service, fault type) combination (RCAEval RE3 has
27 such templates).

**Runs and aggregation (fixed before experiments).**
- r = 5 runs per case for E2b and E3; r = 3 for other LLM arms (budget; see Section 12).
- Per-case score = mean over runs (e.g. top-1 ∈ {0, 0.2, …, 1}).
- Failed runs (LLM/parse error) are retried up to twice; if still failed, scored as incorrect.

**Primary test.** Difference in mean per-case top-1 accuracy, E3 − E2b, on the synthetic test set.
Inference: two-sided paired sign-flip permutation test at **family level** (per-family mean of per-case
differences), 10,000 permutations, α = 0.05; 95% CI by cluster bootstrap (resample families, then
cases). Sensitivity analysis: exact McNemar on per-case majority outcome (≥ 3 of 5 runs correct).

**Secondary.** All other arm comparisons and metrics, with Holm correction; reported per stratum.
Public-set results reported separately, not pooled with synthetic.

**Scope for the submission (D-024).** The test set is 60 cases in 20 families with 3 runs (5 if time
permits). This is **exploratory**: about 58% power for a 15-point difference before clustering. Results
are reported as effect sizes with 95% cluster-bootstrap CIs and permutation p-values as descriptive
statistics; **no claim of statistical significance** is made. Minimum experiment set: E1, E2b, E3,
A2, A3. E2a, E2-oracle, E2-matched, A1, A4, A5, public datasets, dashboard and Docker are deferred.

**Sample size.** Exact McNemar power (α = 0.05) computed for planned sizes, assuming 5% of cases favour
E2b:

| Independent units | +10 pt | +15 pt | +20 pt |
|---|---|---|---|
| 30 | 0.10 | 0.24 | 0.40 |
| 60 | 0.31 | 0.58 | 0.80 |
| 90 | 0.49 | 0.79 | 0.94 |
| 120 | 0.63 | 0.90 | 0.99 |

Target: **≥ 90 test cases across ≥ 30 families**, giving about 80% power for a 15-point difference if
families are not strongly correlated. Family clustering lowers effective sample size; the achieved
design effect is reported. Differences smaller than ~15 points may not be detectable and will be
reported as such.

**Pre-registration.** Primary test, aggregation, strata, filters and exclusion rules are frozen in this
document and committed before test-set runs; the commit hash is cited in the dissertation. Per-case
outputs of every arm are released (2606.29159).

## 12. Compute budget (revised after M2 calibration)

**Measured on this server (M2):** prompt processing ≈ 22–29 tokens/s on CPU (3,337 tokens in 152 s;
3,357 in 118 s); cached identical prefix ≈ 2.6 s. Earlier per-run estimates (E2 ~1.5 min) were too low.

| Arm (60 cases × runs) | Assumption [A] | Per run | Total |
|---|---|---|---|
| E2b, 3 runs | ~3.3k prompt tokens + ~300 output tokens | ~3–3.5 min | ~10 h |
| E3, 3 runs | Conversation prefix cached across turns; final call appended to the same conversation | ~6–9 min | ~18–27 h |
| A2, 3 runs | As E3, fewer gate-forced steps | ~5–8 min | ~15–24 h |
| A3 | Scored from E3 raw output | 0 | 0 |
| **Core total** | | | **~43–61 h** |

This exceeds a safe run window. Reduction options, to be chosen at the pilot freeze with measured
per-run times: B = 2,000 instead of 3,000; A2 at 2 runs; 45 cases (15 families × 3); compact
references for repeated evidence in E3 to keep the conversation short.

## 13. Threats to validity

- **Circular synthetic ground truth:** separate test templates, frozen before tuning; public external-validity sets.
- **Log-only scope:** public logs often lack the fault signal (Section 8.1); results apply to log-manifesting faults.
- **Template dependence:** family-level splits and clustered inference.
- **Single annotator for public evidence labels:** two-pass agreement reported.
- **Small-model ceiling:** results apply to 8B-class local models; a second model gives a sensitivity check.
- **Lexical grounding validator:** precision checked against a manually labelled sample.
- **Single hardware platform:** latency results are hardware-specific and reported as such.
- **Literature recency:** many 2026 sources are preprints; claims of absence are qualified (Section 3).
