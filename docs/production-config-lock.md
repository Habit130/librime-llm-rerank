# Production configuration lock (Squirrel#80)

Lock-only. Uses bound AC-164/71/72/73/78/79 evidence. Does not re-run
walk-forward, ANN qualification, 100k fixtures, or models. Does not
enable live `α`/`γ`/evidence and does not start #81.

## Freeze then decide

`eval/run_production_config_lock.py` writes
`production_config_lock_freeze.json` before any terminal. The freeze
binds snapshot SHA-256, AC-164/78/79 report hashes, cutoff HLC, the
144 finite-H BGE cells, the candidate backends, and the four
production-complete gates. A freeze that already contains `terminal` is
a contract failure.

## Elimination

Every finite-H shortlisted cell × backend is survive/eliminate with the
first failing gate id:

1. `quality_safety_pollution_finite_h`
2. `claimable_plus3pp`
3. `retrieval_equivalence`
4. `latency_memory_disk`

Unmeasured gates never survive. Unclaimable or unmeasured `+3pp` is not
a production Pass. Tie-break runs only on the survivor set.

## Legal terminals

`unique_lock` or `无合格配置`. Either may Pass AC-80-v1. Empty survivors
are `无合格配置`: live `γ` stays 0, prospective confirmation is
`not_opened`, and #81 stays closed. `unique_lock` is the only terminal
that may record a real next-HLC.

## Paths

Private copies: `.local-work/ac80-production-lock/`. Tracked
desensitized freeze/manifest/report:
`eval/production_config_lock/`. Historical AC-157/159/162/164/78/79
artifact directories are not overwritten.
