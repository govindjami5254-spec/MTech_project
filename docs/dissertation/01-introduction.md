# Chapter 1 — Introduction

> **Draft status (2026-11-25).** Written while the frozen test experiment is running; contains no test results.
> **[OPEN]** marks items needing student or supervisor action; **[CITATION NEEDED]** marks statements whose
> source has not been verified; **[PROVISIONAL]** marks text that depends on pending literature work.
>
> Sources: the approved proposal and faculty evaluation (as provided by the student; not stored in the
> repository **[OPEN — add the approved proposal to the project records]**), `docs/literature-review.md` (LR),
> `docs/research-design.md` (RD), `docs/preregistration.md` (PR), `docs/decisions.md` (D-xxx, Q-xxx), and the
> drafts of Chapters 3 and 4.

**Approved title:** *Agentic AI Framework for Real-Time Root Cause Diagnosis and Recommendations Generation in
Ericsson pENM Deployments.* The title is retained unchanged; no change has been approved by the supervisor.
**[OPEN — Q-001, Q-002]** See Section 1.7.

## 1.1 Background and motivation

Modern software platforms, including telecommunications management systems, are built from many interconnected
services, nodes and applications. Each component writes its own operational logs, and a single failure typically
produces errors in many of them. The component that first reports a problem to users is often a downstream symptom:
the original fault may lie several dependency hops away, in a database that has run out of disk space, a service
with an invalid configuration, or a dependency that has stopped responding.

Identifying that original fault, root cause analysis (RCA), is usually performed by engineers who inspect logs
from several components, correlate events in time, follow dependencies and test competing explanations. The volume
of log data makes this slow. One industrial report describes a single 30-minute incident window producing more than
two million log lines, far exceeding what can be given directly to a language model (Log-Insight, arXiv:2607.08529).
Rule-based monitoring detects known error patterns reliably but does not, by itself, separate root causes from
symptoms.

Large language models (LLMs) can read unstructured log text and explain it in natural language, which makes them
attractive for RCA. Two design approaches have emerged in recent work (LR, Part A):

* **Iterative, tool-using agents**, which decide step by step which logs to query next, for example RCAgent
  (arXiv:2310.16340) and the agents evaluated on the OpenRCA benchmark (arXiv:2602.09937; arXiv:2606.27154).
* **Deterministic evidence pipelines followed by a single LLM call**, which reduce the logs to a compact, ranked
  evidence set before asking the model for a diagnosis, for example Log-Insight (arXiv:2607.08529), EviRCA
  (arXiv:2609.19825) and Loom (arXiv:2609.02649).

The two approaches carry different risks. Agents may stop exploring too early or misinterpret the data they retrieve;
a process-level study of RCA agents found these to be the most frequent failures and reported that prompt changes
alone did not resolve them (arXiv:2602.09937). Single-pass pipelines depend entirely on the evidence selected before
the model is called. Both may state conclusions that the cited evidence does not support. In operational settings
there are further constraints: logs may be sensitive, which favours locally hosted models; log text is untrusted and
can contain instructions crafted to manipulate an LLM (arXiv:2604.15368; arXiv:2605.24421); and diagnostic tooling
must not change the system it inspects.

## 1.2 Problem statement

It is not known, for log-based RCA with a small locally hosted model, whether letting the model collect evidence
iteratively produces better diagnoses than a strong single-pass approach that receives a deterministically selected
evidence set, when both are limited to the same amount of evidence. Existing comparisons reviewed for this work
differ in the evidence available to each approach, do not match evidence budgets, mostly use large hosted models
and multi-source telemetry, and report mixed results (LR Part A; RD §2). In addition, it is not known whether
enforcing exploration coverage and claim grounding in code, rather than through prompts, changes the outcome of
iterative diagnosis.

## 1.3 Research gap [PROVISIONAL]

Among the works reviewed (twenty papers read in full and further candidates screened at abstract level; LR), the
closest controlled comparison reports diminishing or negative returns from agentic workflows with locally run open
models, without a matched evidence budget and on multi-source data (arXiv:2601.22208). Other studies compare an
agent with a single call but give the two different evidence (arXiv:2609.19825; arXiv:2609.02649; arXiv:2610.35767;
arXiv:2310.16340), or study single-call diagnosis only (Hussain and Farrukh, Research Square preprint,
DOI 10.21203/rs.3.rs-11401166/v1). Mechanisms related to those implemented here exist: a soft warning against
finishing early (arXiv:2310.16340), deterministic or fuzzy evidence checks (arXiv:2310.16340; arXiv:2606.08590), and
log-borne prompt-injection studies against shell-capable or tool-less systems (arXiv:2604.15368; arXiv:2605.24421).

Within the reviewed works, no study was found that compares iterative and single-pass log-based RCA under the same
evidence and a strictly matched evidence-token budget, with a small local model, while enforcing exploration coverage
and claim-level grounding in code and separating their effects by ablation.

This gap is **provisional**. It must not be presented as established until:

* **[OPEN — Q-014]** manual searches of Google Scholar, IEEE Xplore and the ACM Digital Library are completed
  (automated access to these services was blocked during the review);
* **[OPEN — Q-015]** three IEEE papers identified at abstract level are read in full: Context-RCA
  (DOI 10.1109/jcc72984.2026.00052), whose abstract describes preventing "premature conclusions before sufficient
  evidence is collected" and may overlap the coverage gate; RCAgentOps (DOI 10.1109/aiotc71250.2026.11689122); and
  VerifyRCA (DOI 10.1109/icetis70504.2026.11633469).

Many of the sources are 2026 preprints that have not yet been peer reviewed.

## 1.4 Research aim and objectives

**Aim.** To design, implement and evaluate a controlled, read-only, locally hosted LLM framework for log-based root
cause diagnosis, and to determine under controlled conditions whether iterative evidence collection improves
diagnosis over a strong single-pass approach at an equal evidence budget.

**Objectives.**

1. Review LLM-based and agentic approaches to RCA, log-based diagnosis and the safety of tool-using agents.
2. Implement LogAgent-RCA, with safe log ingestion, exact evidence-token accounting, a rule-based baseline, a strong
   single-pass LLM baseline, an iterative agent with read-only tools, a coverage gate and a grounding validator.
3. Construct a synthetic evaluation data set with root-cause and supporting-evidence ground truth, kept separate from
   all data visible to the diagnosis strategies, with independent development and test families.
4. Fix and record the experimental protocol, including the evidence budget and the statistical analysis, before
   running the test experiment.
5. Measure diagnostic correctness, evidence quality, unsupported claims and computational cost, and the effect of
   removing the coverage gate or the validator.

## 1.5 Research question and hypotheses

> **Research question.** Does iterative evidence collection improve log-based root-cause diagnosis over a strong
> single-pass LLM when both have the same unique-evidence token budget?

Pre-registered hypotheses (PR §1):

* **H1 (primary).** The iterative agent (E3) differs from the strong single-pass LLM (E2b) in diagnostic correctness.
* **H2.** E3 has a lower unsupported-claim rate and a higher grounded-diagnosis rate than E2b.
* **H3.** E3's additional computational cost is measurable and bounded.
* **H4.** Removing the coverage gate (A2) or the grounding validator (A3) changes E3's outcome.

A null result is considered a valid outcome. With 60 test cases in 20 families the study is exploratory, and results
are reported as effect sizes with confidence intervals rather than claims of statistical significance (D-024).

## 1.6 Scope and boundaries of the implemented prototype

### 1.6.1 What is implemented and evaluated

* **Input.** Offline case bundles of log files with an incident description. Only logs are used; no metrics, traces
  or alerts.
* **Data.** Synthetic, vendor-independent logs from a purpose-built generator: 18 development and 60 test cases,
  frozen and checksummed. No Ericsson, employer, customer or production data, documents or infrastructure are used.
* **Model.** One open-weight model (`qwen3:8b`, Q4_K_M) served locally by Ollama on a shared CPU-only server.
* **Strategies.** A rule-based baseline (E1), a log-free floor (E1f), a strong single-pass LLM (E2b), an iterative
  agent (E3), and two ablations (A2 without the coverage gate; A3 without the validator).
* **Output.** A structured report with ranked root-cause hypotheses, claims citing evidence identifiers, evidence gaps
  and brief, advisory recommendations for a human operator.
* **Safety boundary.** Read-only access to the case's logs through three validated query tools; no command execution,
  file modification, network access or remediation; log text treated as untrusted.

### 1.6.2 What is not claimed

* No validation on production systems or real deployment data.
* No diagnosis "in seconds": measured times on the available hardware are minutes per incident (for example, median
  wall-clock times of 462 s for E2b and 750 s for E3 in a development operational check; D-035).
* No automated remediation.
* No claim that one strategy is superior before the test experiment is analysed.
* No claim that the configuration fits a 16 GB laptop; this has not been measured.
* No adversarial evaluation of the safety controls with the LLM (they are implemented and unit-tested only).
* The quality of the generated recommendations is not evaluated (Section 1.8).

### 1.6.3 Items deferred from the approved proposal

| Proposal item | Status in this dissertation |
|---|---|
| Configurable log sources: uploads, incremental/tail-based ingestion, optional SSH adapter | Not implemented; offline case bundles only |
| Rule-based incident detection creating incident candidates | Not part of LogAgent-RCA; incidents are given in the case bundle (an exploratory prototype contained detection rules but is not evaluated) |
| Web dashboard for incident review and ad-hoc questions | Deferred |
| Public datasets | Reviewed; deferred (none checked provided log-only evidence ground truth at scale) |
| Adversarial safety tests (prompt injection through logs, unauthorised tool access) evaluated with the LLM | Controls implemented and unit-tested; LLM-based evaluation deferred |
| Further baselines and ablations (naive single pass, oracle evidence, compute-matched, other component removals) | Deferred (D-024) |
| Docker packaging, laptop validation, speed optimisation | Deferred to after the controlled experiment |

## 1.7 Title and terminology

* **"Ericsson pENM Deployments".** The implemented and evaluated system is vendor-independent and uses only synthetic
  data. **[OPEN — Q-001]** The supervisor should confirm whether the title is kept, and how the vendor-specific wording
  relates to the vendor-independent scope.
* **"Real-Time".** The measured diagnosis latency is in minutes on CPU-only hardware. **[OPEN — Q-002]** The intended
  meaning (for example, real-time incident detection with near-real-time diagnosis) requires supervisor
  clarification, or the title should be revised.
* **Name.** The implementation is called **LogAgent-RCA** throughout. The proposal used "AgentRCA"; the name was
  changed because an unrelated system with that name exists (arXiv:2607.22385; D-006).

## 1.8 Contributions

The contributions are limited to what has been implemented and is being evaluated. They are positioned relative to the
works reviewed, and their novelty is provisional (Section 1.3).

1. **A controlled comparison protocol** for iterative and single-pass LLM-based RCA in which both strategies share the
   model, prompts, output schema and validator, and are limited by the same strict unique-evidence token budget,
   counted exactly with the model's tokenizer; processed tokens and other costs are measured separately. The protocol,
   including the budget rule and the statistical analysis, was pre-registered before the test experiment.
2. **Two controller-level mechanisms**, implemented in code rather than prompts and evaluated by ablation: a coverage
   gate that refuses to let the agent finish while components with pre-incident problems remain unexamined, and a
   claim-level grounding validator that removes fabricated citations and claims not supported by their cited evidence.
3. **A synthetic log-based RCA test bed** with root-cause, key-evidence and propagation-path ground truth, independent
   development and test families, enforced separation of ground truth from agent-visible data, and frozen, checksummed
   splits.
4. **A read-only safety boundary** for an LLM diagnosis agent (tool allowlist, argument validation, untrusted-input
   handling, audit logging), implemented and unit-tested; it is not adversarially evaluated in this study.
5. **Empirical results** from the frozen test experiment: **[PENDING — to be written after the analysis; no result is
   claimed here]**.

## 1.9 Dissertation structure

| Chapter | Content | Status |
|---|---|---|
| 1 Introduction | Motivation, problem, gap, aims, research question, scope, contributions | This draft |
| 2 Literature Review | LLM-based and agentic RCA, log-based diagnosis, evidence grounding, agent safety | **[PLANNED]** from `docs/literature-review.md`; pending Q-014, Q-015 |
| 3 Research Methodology | Design, arms, data, evidence budget, metrics, statistics, procedure, ethics | Draft (`03-research-methodology.md`) |
| 4 System Design and Implementation | Architecture and modules M1–M11 of LogAgent-RCA | Draft (`04-system-design-implementation.md`) |
| 5 Results | Test-experiment results | **[PENDING]** test analysis |
| 6 Discussion | Interpretation, threats to validity, limitations | **[PENDING]** |
| 7 Conclusion and Future Work | Answers to the research question; deferred items | **[PENDING]** |

---

## Contradictions and inconsistencies found while drafting

| # | Between | Inconsistency | Suggested resolution |
|---|---|---|---|
| 1 | Title ↔ scope | Title names "Ericsson pENM Deployments"; implementation is vendor-independent and synthetic-only | Supervisor decision (Q-001) |
| 2 | Title ↔ measurements | "Real-Time" vs. measured minutes per incident | Define the term or revise the title (Q-002) |
| 3 | Title ↔ evaluation | "Recommendations Generation" is in the title, but recommendations are short advisory text and are not evaluated by any metric | State this limitation explicitly or agree an evaluation with the supervisor **[OPEN]** |
| 4 | Proposal ↔ implementation | Proposal objective "configurable log sources and rule-based incident detection" (uploads, tail-based ingestion, optional SSH); LogAgent-RCA reads offline bundles and has no detection module | Report as deferred (Section 1.6.3) |
| 5 | Proposal ↔ implementation | Web dashboard promised as a deliverable; not built | Deferred; confirm with supervisor whether a demonstration is required |
| 6 | Proposal and faculty feedback ↔ preregistration | Adversarial safety testing (prompt injection via logs, unauthorised tools) requested; only unit tests exist, no LLM-based safety experiment | Describe as implemented and unit-tested, or run a separate safety experiment after the test runs (would need compute time) **[OPEN]** |
| 7 | Proposal ↔ implementation | Public datasets planned alongside synthetic data; synthetic only | Deferred with reasons (RD §8.1) |
| 8 | Faculty feedback ↔ preregistration | Ablations described as mandatory; only A2 and A3 are run (A1, A4, A5 deferred) | Report the reduction and its reason (D-024) |
| 9 | Research design ↔ preregistration | RD lists RQ1–RQ4 (including a safety research question) and arms E2a, E2-oracle, E2-matched; the preregistration has one RQ, hypotheses H1–H4 (H4 about ablations) and no such arms | Treat the preregistration as authoritative; mark RD sections as superseded **[OPEN]** |
| 10 | Decision D-016 ↔ evaluation | Contribution 4 was "safety evaluation"; what is delivered is implemented, unit-tested controls | Wording in Section 1.8 adjusted accordingly |
| 11 | Proposal ↔ implementation | Proposal name "AgentRCA"; implementation "LogAgent-RCA" | Explained in Section 1.7 |
| 12 | Proposal ↔ run plan | Proposal asked for repeated LLM runs; the plan uses 2 runs per LLM arm (3 or more were planned earlier) | Report with the compute rationale (D-034) |
