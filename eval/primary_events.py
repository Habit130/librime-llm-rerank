#!/usr/bin/env python3
"""Primary-denominator event loading for the #106 α recalibration.

The primary denominator (spec #43 / #76 rewrite, frozen in this contract):

- events with HLC >= the freeze watermark, unretracted, replayable;
- **group-complete** = the saved same-group competition size is `< N`
  with `N = 32` (window), NOT the persisted ``competition_complete`` bit;
- 上文 = the stored ``preceding_text`` (already the last 64 Unicode
  characters, asserted <= 64); empty 上文 is a valid window, stays in the
  primary set, and is reported as a stratum — it is not a fault;
- labels = the user's ``final_selection_text``.

Event loading reuses ``walkforward.FrozenFacts`` (HLC total order,
retraction as-of, read-only snapshot) so the causal semantics match #70.
"""

import os
import sqlite3
from typing import Dict, List, Optional, Tuple

from walkforward import FrozenFacts, SelectionEvent

# Freeze watermark (dev-target start, inclusive): #75 freeze record.
FREEZE_WATERMARK: Tuple[int, int] = (1786806466751, 0)
# Window size for the group-complete gate (spec #43 / #76, N=32).
GROUP_COMPLETE_N = 32
# ADR-0002: the stored preceding_text window.
PRECEDING_WINDOW = 64


class EventLoadingError(Exception):
    """A true fault in primary event loading."""


def _group_complete(event: SelectionEvent, n: int = GROUP_COMPLETE_N) -> bool:
    """Group-complete: saved same-group competition size < N.

    This is the #76 rewrite gate, NOT the persisted ``competition_complete``
    bit: a saved window of fewer than N candidates means the whole group was
    materialized and the recorded competition set is the complete choice
    problem.
    """
    return len(event.competition) < n


def load_primary_events(
        snapshot_path: str,
        freeze_watermark: Tuple[int, int] = FREEZE_WATERMARK,
        group_complete_n: int = GROUP_COMPLETE_N,
) -> Dict:
    """Load the primary denominator from one frozen snapshot.

    Returns a dict:

        {
          "events": [SelectionEvent, ...] in HLC order, group-complete and
                    at-or-after the freeze watermark, unretracted,
          "counts": {
              "post_freeze_active": int,
              "post_freeze_group_complete": int,
              "group_complete_n": int,
              "freeze_watermark": [physical, logical],
              "empty_preceding": int,     # within the returned events
              "overlong_preceding": int,  # must be 0 (assertion)
          },
          "identity": the snapshot meta identity,
        }

    Retracted events and events with HLC < the watermark never enter the
    returned set (SCN-106-2).  Empty 上文 stays in the set and is counted
    (SCN-106-7).  Any stored preceding_text longer than 64 characters is a
    fault (ADR-0002 assertion).
    """
    facts = FrozenFacts(os.path.abspath(snapshot_path))
    try:
        identity = facts.identity()
        all_events = facts.events()  # HLC order, active + retracted
        post_freeze_active = 0
        result = []
        empty_preceding = 0
        overlong = 0
        for event in all_events:
            if event.retracted:
                continue
            if event.hlc < freeze_watermark:
                continue
            post_freeze_active += 1
            if not _group_complete(event, group_complete_n):
                continue
            if len(event.preceding_text) > PRECEDING_WINDOW:
                overlong += 1
            if not event.preceding_text:
                empty_preceding += 1
            result.append(event)
        if overlong:
            raise EventLoadingError(
                "%d primary events have preceding_text longer than %d "
                "characters (ADR-0002 violated)" % (overlong,
                                                    PRECEDING_WINDOW))
        return {
            "events": result,
            "counts": {
                "post_freeze_active": post_freeze_active,
                "post_freeze_group_complete": len(result),
                "group_complete_n": group_complete_n,
                "freeze_watermark": list(freeze_watermark),
                "empty_preceding": empty_preceding,
                "overlong_preceding": overlong,
            },
            "identity": identity,
        }
    finally:
        facts.close()
