#!/usr/bin/env python3
"""3000-milestone exact suffix walk-forward driver (Habit130/squirrel#164).

Forwards to the AC-159 seam with ``--delivery ac164``.  The preserved
AC-162 snapshot is mandatory; a live backup is refused.

Usage:

    python3 eval/run_suffix_walkforward_ac164.py \
        --snapshot <isolated AC-162 snapshot copy> \
        --work-dir <repo>/.local-work/ac164-3000-walkforward/work \
        --artifact-dir <repo>/.local-work/ac164-3000-walkforward/artifacts
"""

import sys
from pathlib import Path

if str(Path(__file__).resolve().parent) not in sys.path:
    sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_suffix_walkforward import main as ac159_main  # noqa: E402


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    if "--delivery" not in argv:
        argv = ["--delivery", "ac164", *argv]
    if "--snapshot" not in argv and "--fixture" not in argv:
        print("environment blocker: AC-164 requires --snapshot of the "
              "preserved AC-162 snapshot; refuse a live backup",
              file=sys.stderr)
        return 3
    return ac159_main(argv)


if __name__ == "__main__":
    sys.exit(main())
