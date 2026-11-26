# Chapter 2 — Literature Review

> **Draft status (2026-11-25).** Based on `docs/literature-review.md` (LR). Sources in LR Part A (A1–A20) were read
> in full once; quotations and figures below are taken from those notes. Sources in LR Part B were screened at
> **abstract level only** and are marked *(abstract only)*; they must not be cited as verified until read in full.
> **[OPEN]** marks pending work; **[CITATION NEEDED]** marks a statement without a verified source. The research gap
> in Section 2.10 is **[PROVISIONAL]** until the open searches (Q-014) and full-text reviews (Q-015) are completed.

## 2.1 Introduction and review method

This chapter reviews work on diagnosing failures in software and cloud systems with large language models (LLMs),
concentrating on four questions that shape the design of LogAgent-RCA: (1) how single-pass and iterative (agentic)
LLM diagnosis compare; (2) how diagnosis claims are grounded in evidence; (3) how complete exploration is ensured;
and (4) how LLM systems that read logs can be manipulated.

**Search.** Searches were run between 19 and 21 November 2026 using the arXiv API (two rounds), Crossref
(restricted to IEEE and ACM publications), OpenAlex and Semantic Scholar (mostly rate-limited; 4 of 19 queries
answered). Automated access to Google Scholar, IEEE Xplore, the ACM Digital Library and DBLP was blocked. Query
terms combined root cause analysis, incident diagnosis, LLM, agent, logs, single-pass, small or local models,
hallucination, evidence grounding and prompt injection. Candidates were screened by title and abstract; the most
relevant were read in full and checked against a fixed list of questions (data modalities, models, baselines and
whether they receive the same evidence and budget, ablations, grounding, safety, statistics, cost).

**Limitations of the review.** Many sources are 2026 preprints that have not been peer reviewed. Each full-text
paper was read once. **[OPEN — Q-014]** Manual searches of Google Scholar, IEEE Xplore and ACM DL are outstanding.
**[OPEN — Q-015]** Three IEEE papers that may overlap this work (Section 2.6, 2.7) are known only from abstracts.

## 2.2 Root cause analysis and its evaluation

Root cause analysis in microservice and cloud systems has traditionally used statistical, causal or graph methods
over metrics and traces, alongside rule-based monitoring of logs **[CITATION NEEDED — survey of classical RCA
methods; candidate surveys identified at abstract level: ACM CSUR DOI 10.1145/3746635; arXiv:2406.11213; LLM4Log,
TOSEM DOI 10.1145/3842759]**.

Two evaluation lessons from recent work shape this study's protocol.

* **Honest baselines.** In a controlled study on the RCAEval benchmark, a ranker that read no telemetry placed the
  true culprit in its top five on 99.7% of in-distribution incidents, because faults were injected into only a few
  services per system; this collapsed to Avg@5 0.192 across systems (Buljić, arXiv:2609.27069). The same paper gives
  a twelve-item checklist that includes computing significance "over independent folds, never over repeated
  measurements" and writing "the decision rule down before you have the result". These motivate the log-free floor
  E1f, case-level statistics and the pre-registration used in this dissertation (Chapter 3).
* **Outcome versus process.** OpenRCA 2.0 (Fang et al., arXiv:2606.27154) annotates causal propagation paths. Across
  11 frontier models, agents recovered the exact root-cause set in 20.7% of cases on average, named at least one
  correct root-cause service in 76.0%, but linked it to the symptom through a propagation path in 61.5%; scoring only
  the final answer hides this "ungrounded diagnosis". This motivates the *grounded* metric and the evidence-coverage
  metric used here.

Benchmarks with logs exist (for example RCAEval, OpenRCA), but most were built from multi-source telemetry, and the
review of their suitability for log-only RCA is summarised in Section 2.9.

## 2.3 Single-pass and pipeline approaches

Several systems reduce telemetry deterministically and then call an LLM once (or a fixed number of times):

* **RCACopilot** (Chen et al., arXiv:2305.15778; EuroSys '24) matches incidents to handler workflows built by
  on-call engineers, collects diagnostic data, summarises it with GPT-4 and predicts a root-cause category from
  retrieved examples. On a private data set of 653 incidents it reports micro-F1 0.766 and macro-F1 0.533 (the
  abstract's "accuracy up to 0.766" is micro-F1).
* **Log-Insight** (arXiv:2607.08529) applies a six-stage symbolic pipeline to log tables (sampling, schema inference,
  compression, contrastive error-vs-success statistics) and gives an enterprise LLM a compact "Forensic Case File".
  On 11 private production incidents (110 runs) it reports MRR 0.790 at a mean latency of 27 s. It has no agentic
  baseline and does not measure evidence accuracy. Its design is the template for the strong single-pass baseline
  E2b.
* **MicroRCA-Agent** (Tang et al., arXiv:2509.15635), despite its name, is a fixed multimodal pipeline. Its modality
  ablation scored 23.59 with logs alone against 50.71 with logs, traces and metrics, an indication of the ceiling of
  log-only diagnosis on that benchmark.
* **EviRCA** (arXiv:2609.19825) converts telemetry into deterministic "evidence cards" and lets an LLM reason over them
  with read-only tools. It reports 43.9% and 40.6% correct with two hosted models, and argues that iterative agentic
  exploration is costly, unstable and less accurate. In its own experiments, however, the single-call baseline and the
  iterative baseline received different evidence, no repeated runs were reported, and EviRCA itself is partly
  iterative (its worked example uses five tool steps).
* **Loom** (Begleiter et al., arXiv:2609.02649) combines heuristic hypotheses into one LLM synthesis call. It matched an
  iterative agent on two of four OpenRCA subsets and was about 26 times faster on one subset; the two systems received
  different evidence.
* **TriFleetRCA** (arXiv:2609.23766) runs a 14B model locally after template de-duplication and lexical ranking of log
  lines, with a median latency of 1.6 s; cited evidence identifiers are resolved to lines but graded only offline.
* **Single-call accuracy decomposition.** Hussain and Farrukh (Research Square preprint,
  DOI 10.21203/rs.3.rs-11401166/v1) varied the text given to one single-call system on RCAEval and attributed most of
  its accuracy to the evidence rather than the prompt; removing log text reduced accuracy on code-level faults from
  0.600 to 0.356. They state that "agents that call tools, iterate or retrieve may behave differently".
* **Fine-tuned small models.** A 4B model trained with preference optimisation outperformed larger systems on several
  data sets (arXiv:2611.02416); this relies on training and lies outside the zero-shot scope of this work.

## 2.4 Iterative and agentic approaches

Tool-using agents interleave reasoning and actions, following the ReAct pattern (Yao et al., arXiv:2210.03629
**[OPEN — not reviewed in full; cite as the originating paper after checking]**).

* **RCAgent** (Wang et al., arXiv:2310.16340; CIKM '24) runs a controller agent with expert sub-agents on a locally
  deployed 13B model (Vicuna-13B on vLLM), motivated by data privacy. It outperforms ReAct and, online, an "LLM
  Summary" baseline whose input was truncated to fit the model's context, while "utilizing more data and consuming more
  resources". It warns the agent against "early finalizing without thorough investigation" (criteria unstated) and
  discards sub-agent analyses whose evidence cannot be fuzzy-matched to the logs.
* **Roy et al.** (arXiv:2403.04123; FSE '24 companion) compared a ReAct agent (GPT-4) with retrieval baselines on 500
  private incidents under a cap of ten retrieved documents: correctness was similar (35% vs. 39%), while hallucination
  was lower for the agent (4% vs. 12–40%).
* **OpenRCA agents.** A process-level analysis of 1,675 runs of the OpenRCA controller–executor agent across five
  models (Kim et al., arXiv:2602.09937) found hallucinated data interpretation in 71.2% and incomplete exploration in
  63.9% of runs, persisting across models; two prompt-engineering strategies "neither produced a meaningful
  improvement". The authors propose verification modules as future work.
* **Graph-guided agents.** An auditable Kubernetes RCA agent (arXiv:2606.08590) uses a read-only tool allowlist and a
  deterministic validation stage; in its own analysis the validator accepted a false root cause, and the true node
  remained unvisited when its bounded traversal ended.
* **Free agents vs. prescribed workflows.** Bi et al. (arXiv:2610.35767) found that simple harnesses with frontier models
  (a SQL agent, a coding agent and a one-shot call) outperformed five published RCA agents, and that agents with more
  prescribed steps scored lower. The authors note this is correlational. This is a counter-argument to enforcing
  investigation steps, relevant to the coverage gate (Section 2.7).
* A system also named **AgentRCA** (Wei and Fink, arXiv:2607.22385) applies a tool-using agent to industrial sensor
  data with a 30B model; it is unrelated to log-based RCA, and the name clash motivated naming this implementation
  LogAgent-RCA.

## 2.5 Comparisons of agentic and single-pass diagnosis

The question studied in this dissertation has been addressed only partially. Table 2.1 summarises the comparisons found.

**Table 2.1 — Agent versus single-pass comparisons in the reviewed literature**

| Study | Models | Data | Same evidence for both? | Budget matched? | Finding |
|---|---|---|---|---|---|
| Riddell et al., arXiv:2601.22208 (FORGE '26) | Local open models, 3B–104B | GAIA, OpenRCA (multi-source) | Same information, different form (full knowledge graph vs. tool access) | No | Agentic workflows show "diminishing or negative returns"; a 4B model used its tools in 23.4% of runs |
| Roy et al., arXiv:2403.04123 | GPT-4 | Private incidents | Agent had extra raw-description access | Document count only | Similar correctness; fewer hallucinations for the agent |
| RCAgent, arXiv:2310.16340 | Local 13B | Private (logs plus other sources) | Baseline input truncated | No | Agent better |
| Loom, arXiv:2609.02649 | Hosted; 8B variant | OpenRCA | No | No | Comparable on 2 of 4 subsets, much faster |
| EviRCA, arXiv:2609.19825 | Hosted | OpenRCA | No | No | Single call ≥ iterative baseline |
| Bi et al., arXiv:2610.35767 | Hosted frontier models | 90 public cases (all with metrics) | One-shot evidence rule-selected | Wall-clock time, not tokens | Free agents > one-shot > published agents |
| Gopal and Krishnan, arXiv:2607.13548 | GPT-5.2 | OpenRCA | Identical among pipeline arms; the agent "not input-matched" | Tokens not recorded | Procedure and rules matter |
| HERO, ASE 2026, DOI 10.1145/3832783.3837509 *(abstract only)* | — | OpenRCA | — | — | Hypothesis-centred agent vs. workflow and ReAct agents |

Results are mixed, and none of these comparisons equalises a token budget for the evidence given to each strategy.
The closest study (arXiv:2601.22208) suggests that, for small local models, agentic workflows may not help, which makes
a null result for this dissertation's research question plausible.

## 2.6 Evidence grounding and hallucination

Unsupported or invented claims are a recurrent failure. Agents misinterpret retrieved data (arXiv:2602.09937); agents
name correct services without a grounded propagation path (arXiv:2606.27154); a modality-ablated pipeline produced a
reasoning chain about trace data it had not received (arXiv:2509.15635). Mechanisms reported in the literature
include:

* fuzzy matching of a sub-agent's quoted evidence against the logs, discarding unmatched analyses (RCAgent,
  arXiv:2310.16340);
* a deterministic check that a cited fault signal resolves to an observed record (arXiv:2606.08590);
* re-executing cited queries at evaluation time, without checking whether the result supports the claim
  (arXiv:2606.27154);
* resolving cited log-line identifiers, graded offline (arXiv:2609.23766);
* *(abstract only)* non-LLM verifiers and rule-based critics in IEEE 2026 papers: VerifyRCA
  (DOI 10.1109/icetis70504.2026.11633469), VerifyOps (DOI 10.1109/mlise70044.2026.11607508) and RCAgentOps
  (DOI 10.1109/aiotc71250.2026.11689122) **[OPEN — Q-015: read in full]**.

Validation of evidence is therefore not new as a mechanism. What the reviewed works do not report is validation of
every claim in the final diagnosis inside the pipeline, applied identically to competing strategies, with its effect
measured by ablation; that is how the validator is used in this dissertation **[PROVISIONAL]**.

## 2.7 Exploration coverage

Incomplete exploration is the second most frequent agent failure reported in arXiv:2602.09937, and small models in
arXiv:2601.22208 often stopped using tools. Approaches found are prompt-level instructions to examine all anomalies
(arXiv:2607.13548), a soft warning against early finalising (arXiv:2310.16340), and bounded search, which does not
guarantee coverage (arXiv:2606.08590). Two IEEE papers known only from abstracts describe stronger mechanisms:
Context-RCA (DOI 10.1109/jcc72984.2026.00052) aims to "prevent premature conclusions before sufficient evidence is
collected", and RCAgentOps applies "coverage checks" in a critic stage. Whether either enforces coverage in code is
unknown **[OPEN — Q-015; Context-RCA has priority]**. Against enforcement, arXiv:2610.35767 found that more prescribed
investigation steps coincided with lower accuracy. The coverage gate in LogAgent-RCA is therefore evaluated by
ablation (A2), and a negative effect is a possible outcome.

## 2.8 Small, locally hosted models

Local deployment is motivated in several works by data privacy (arXiv:2310.16340; arXiv:2601.22208). Locally run or
small models in the reviewed literature include Vicuna-13B (arXiv:2310.16340), 3B–104B open models
(arXiv:2601.22208), an 8B synthesiser (arXiv:2609.02649), a fine-tuned 4B model (arXiv:2611.02416), a 14B model
(arXiv:2609.23766) and a 30B mixture-of-experts model (arXiv:2607.22385). Small local models are therefore not novel on
their own; in this dissertation they are part of the setting.

## 2.9 Safety of LLM systems that read logs

Logs can carry attacker-controlled text. **LogJack** (arXiv:2604.15368) placed 42 payloads in cloud logs and measured
whether debugging agents with shell access proposed the injected commands; one 70B model did so in 86.2% of trials,
and input guardrails detected almost none. Read-only agents were outside its scope. **Poisoning the Watchtower**
(arXiv:2605.24421) showed that log text can steer the conclusions of a tool-less security analyst model; defences
reduced but did not remove the effect. Further studies are known at abstract level only: telemetry manipulation
against AIOps agents (arXiv:2508.06394), injections in log fields against 8–20B models
(Zenodo DOI 10.5281/zenodo.23808719), data exfiltration from a local 7B agent (DOI 10.1109/eit68936.2026.11670372)
and injection through tool metadata (arXiv:2610.36108). None of the full-text sources evaluated a read-only,
allowlisted RCA agent against ground truth for diagnosis steering. LogAgent-RCA implements read-only controls and
injection handling (Chapter 4), but an adversarial evaluation of them is not part of this study.

### 2.9.1 Data sets for log-only RCA

A review of public data sets (RD §8.1) found that none provided supporting-evidence labels at scale. RCAEval's RE3
subset (code-level faults diagnosable from stack traces) and the Nezha data set were judged the most suitable; several
others recorded faults mainly in metrics or traces, had licence conflicts, or leaked labels through log content
**[OPEN — Q-016]**. This led to the synthetic test bed described in Chapter 3.

## 2.10 Summary and research gap [PROVISIONAL]

**Table 2.2 — Coverage of the elements of this study in the full-text sources** (Y yes, P partly, N no; LR Part A)

| Element | Studies that cover it fully or partly |
|---|---|
| (i) Agent vs. single pass with the same evidence and a matched token budget | Partly: arXiv:2601.22208, 2403.04123, 2310.16340, 2609.02649, 2610.35767; none matched a token budget |
| (ii) Small locally hosted models | arXiv:2310.16340 (Y), 2609.23766 (Y); partly 2601.22208, 2609.02649, 2611.02416, 2607.22385 |
| (iii) Log-only RCA | arXiv:2607.08529 (Y); partly 2310.16340, 2509.15635 |
| (iv) Code-level coverage enforcement | Partly: arXiv:2310.16340 (soft warning), 2607.13548 (prompted); *(abstract only)* Context-RCA, RCAgentOps |
| (v) In-pipeline claim–evidence validation | Partly: arXiv:2310.16340, 2606.08590, 2606.27154, 2609.23766; *(abstract only)* VerifyRCA, VerifyOps, RCAgentOps |
| (vi) Adversarial safety testing | arXiv:2604.15368, 2605.24421 (Y, different settings); partly 2606.08590, 2609.23766 |

Within the works reviewed, no study was found that combines elements (i)–(v): a comparison of iterative and
single-pass log-based RCA under the same evidence and a strictly matched evidence-token budget, with a small local
model, enforcing exploration coverage and claim-level grounding in code, and measuring each mechanism by ablation.
Element (vi) is addressed in this dissertation only through implemented and unit-tested controls.

This statement is provisional and limited to the reviewed works. It will be finalised only after the manual
searches (Q-014) and the full-text reading of Context-RCA, RCAgentOps and VerifyRCA (Q-015). If Context-RCA enforces
evidence sufficiency in code, the coverage-gate element must be described as related prior work rather than as a gap.

---

### Open items for this chapter

| Ref | Item |
|---|---|
| Q-014 | Manual Google Scholar / IEEE Xplore / ACM DL searches; record date, database and hit counts |
| Q-015 | Full text of Context-RCA (priority), RCAgentOps, VerifyRCA (CC-BY on IEEE Xplore; browser download) |
| — | ReAct (arXiv:2210.03629): confirm and cite properly; not reviewed in full |
| — | Classical RCA background: verified survey citation needed |
| — | Author names are given only where recorded in LR; complete bibliographic entries (authors, venues) for all sources |
| — | Abstract-only sources (Part B) must be read before being cited as findings |
| Q-016 | Public data sets: licence conflicts and future work |
