#!/usr/bin/env bash
set -euo pipefail

root="$(cd "$(dirname "$0")/.." && pwd)"
cd "${root}"
python="${1:-python3}"

"${python}" -m unittest discover -s daemon -p 'test_*.py'
"${python}" -m unittest discover -s eval -p 'test_*.py'
