# Actionable Milestone Census (AC-162-v1)

- Engine: actionable-milestone-census-v1
- Contract: AC-162-v1
- Code SHA: `c817a86cd3fe0479155066c556ce3da92647278c`
- Snapshot SHA-256: `111517b4548ad97cb73c801a3099076d70f90afc36bf94eb13f3fd1121cd94f5`
- Snapshot identity: history `dc3ffbf1a21957e0bb4ceed535c9df56` / epoch `8407bd6b456ba5c5a526b4b95951bac3`
- Route: `dedicated_qwen3_embedding_0_6b`
- Cutoff HLC: `[1787667799562,0]` (prefix inclusive)
- Prefix events: 4844 (sha256 `e50349a8630a9505c667569bde93c5bbfc9b1206d28c51d0ec5c80d96bb201a1`)
- Suffix events: 3901 (sha256 `9a7dd8b9444a397431a6c0212cfa2379dcfdac5f5a1cefc7150a1324cf3bb7a2`)

## Counts

```json
{
  "prefix": {
    "replayable": 4844,
    "group_complete": 3326,
    "actionable_group_complete": 2537,
    "actionable_keys": 421
  },
  "suffix": {
    "replayable": 3901,
    "group_complete": 2694,
    "actionable_group_complete": 2370,
    "actionable_keys": 479
  },
  "total": {
    "replayable": 8745,
    "group_complete": 6020,
    "actionable_group_complete": 4907,
    "actionable_keys": 611
  }
}
```

## Terminal

```json
{
  "outcome": "reached_3000",
  "threshold": 3000,
  "remaining": 0,
  "reason": "total actionable group-complete events 4907 >= 3000; the predeclared AC-162 milestone is reached; the walk-forward is NOT started by this census"
}
```

## Reference semantics

```json
{
  "tau": 0.0,
  "k_evidence": 8,
  "half_life": "inf",
  "saturation_k": 1.0,
  "gamma": 0.0,
  "actionable": "any(s > 0)",
  "group_complete_n": 32,
  "payload_rule": "last64(preceding)+candidate",
  "query_instruction": "Represent the candidate-conditioned query for semantic retrieval.",
  "event_side_instruction": "none",
  "ac159_seam": "AC-159-v1/suffix-walkforward-v2"
}
```

## AC-159 reference (quoted, not re-verified)

```json
{
  "snapshot_sha256": "4aebca791976c520d749525e177e2c6769a999290e5d49a58001f5a99f4359e9",
  "prefix_actionable_group_complete": 2537,
  "suffix_actionable_group_complete": 13,
  "total_actionable_group_complete": 2550
}
```

## Notes

- the census reports the fresh claim-time counts; drift vs the accepted AC-159 2537/13/2550 is expected and reported, never forced (RISK-CENSUS3000-1)
- L28 and BGE routes are intentionally outside this gate: AC-159's canonical top-level data count used the first Qwen3-Embedding route (RISK-CENSUS3000-2)
- no grid, quality gate, shortlist, ANN, deployment or live alpha/gamma/evidence change occurred (CENSUS3000-7)

## Decision record

- d1 snapshot: one fresh read-only Online Backup at claim (CENSUS3000-1); the live store is never written; status continuity is checked when the status CLI is available
- d2 route: exactly dedicated_qwen3_embedding_0_6b; payload last64(preceding)+candidate; frozen English query instruction on the query side only, no event-side instruction (AC-159 first-route semantics)
- d3 parameters: tau=0, K_evidence=8, H=inf, saturation_k=1, gamma=0; actionable = any(s > 0) — gamma zero preserves the shadow order but does not redefine actionability
- d4 group-complete: saved same-group competition size < 32; the persisted competition_complete bit is never the gate (#76/#77 rewrite)
- d5 split: prefix = hlc <= [1787667799562,0] inclusive, suffix = strictly later; the cutoff is never moved to the new snapshot maximum (CENSUS3000-5)
- d6 terminal: reached_3000 iff total actionable group-complete >= 3000, else pending_3000 with the exact remaining count; the walk-forward is not started by this census (CENSUS3000-4)

Report SHA-256: `78489993b52d14c6de8024cbe125b0396e168e2c341ab8f2097c0ff86466d893`