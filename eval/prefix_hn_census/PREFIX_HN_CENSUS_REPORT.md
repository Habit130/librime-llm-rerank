# Prefix Hard-Negative Query Census (AC-158-v1)

- Engine: prefix-hn-census-v1
- Contract: AC-158-v1
- Code SHA: `cc746031ad1c2d1fcd461395598f99766de420ae`
- Snapshot SHA-256: `aa39556a984ebf6b18c416b348882a1aa2c243f4d8853541d3177f1a0b2fb394`
- Snapshot identity: history `dc3ffbf1a21957e0bb4ceed535c9df56` / epoch `8407bd6b456ba5c5a526b4b95951bac3`
- Cutoff (max unretracted HLC, inclusive): `[1787667799562,0]`
- Prefix events: 4844 (sha256 `500183579a2cb54facbe7b1fb147416bad698bc5012daa8ef292733b5694aed6`)
- In-snapshot suffix events: 0 (definition)
- Primary hard-negative queries: **760** (threshold 200)
- #77-wide diagnostic: 760
- Terminal: **可标定**

## Data state (new prefix)

```json
{
  "replayable": 4844,
  "group_complete": 3326,
  "keys": 791,
  "explicit_indexed": 218,
  "rank_gt1": 234,
  "coverage": 0.6866226259289843
}
```

## Hard-negative definition

- prefix_hard_negative_query_count (calibration_cc): same choice-problem key, HLC earlier, unretracted, differing final selection, and that selection in the current competition set
- #77-wide count (no current-competition filter) is diagnostic only and never chooses the terminal

## Terminal

```json
{
  "outcome": "可标定",
  "threshold": 200,
  "reason": "primary hard-negative query count 760 >= 200; walk-forward is NOT started by this census"
}
```

## Notes

- walk-forward is NOT started by this census; 可标定 only unlocks a later freeze contract
- no model forward, no grid scan, no live α/γ change (AC-158-6)
- the #77 prefix upper bound [1787065441087,0] is not used as the new prefix upper bound (issue #158 body)

## Decision record

- d1 cutoff: new prefix upper bound = max unretracted HLC in the pinned snapshot, inclusive (AC-158-2); every unretracted event is in the new prefix, in-snapshot suffix count is 0 by definition
- d2 primary count: frozen prefix_hard_negative_query_count on those prefix targets; threshold 200 unchanged (AC-158-3)
- d3 terminal: 可标定 (primary >= 200) | 仍不可标定 (primary < 200); the #77-wide appendix never chooses the terminal

Report SHA-256: `a39f188e5c43bfcc809dcc3bfc6c9bebbee08a9d9cb5b2708772a3810be527a3`