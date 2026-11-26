# Test experiment status: INTERRUPTED and INCOMPLETE

The frozen test experiment (`python -m logagent_rca run --config configs/test.yaml`, code commit `c5448ef`,
tag `test-freeze`, config hash `f084f650…3ca1`) was **stopped on request on 2026-11-26 at about 08:56 IST** so the
project could be preserved and pushed. It is **incomplete**.

* Started: 2026-11-25 19:07 IST (13:37 UTC).
* Completed: **147 of 480 planned runs**, all with status `ok`. Every run was repeat `r0`.
  * Cases `test-c001`–`test-c029`: all five arms (E1, E1f, E2b, E3, A2), repeat r0.
  * Case `test-c030`: E1 and E1f only.
  * Cases `test-c031`–`test-c060`: not started. No repeat-r1 run has been made for any case.
* The run in progress when it was stopped (`test-c030__E2b__r0`) was discarded. Records are written atomically, so
  no partial record exists.
* `memlog.txt` is the host memory log written once a minute during the experiment.

**These are not final research results.** They cover half the cases and one of the two planned repeats for each
LLM arm, so the pre-registered analysis (`docs/preregistration.md`) does not apply to them yet. Do not report
scores computed from this directory as findings.

To resume, use the same frozen code and keep Ollama running. The runner skips runs that already have a record. On
the development server, the original frozen working tree still holds this directory (untracked) and can resume in
place. From a fresh clone:

```bash
git worktree add ../logagent-frozen test-freeze          # exact code and config of the recorded runs
cp -a results/test-main ../logagent-frozen/results/      # carry over the completed records
cd ../logagent-frozen    # create .venv and the tokenizer as described in docs/web/README.md, then:
.venv/bin/python -m logagent_rca run --config configs/test.yaml >> results/test-main/run.log 2>&1
```

The interruption and the resume must be recorded as deviations in the dissertation.
