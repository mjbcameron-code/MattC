#!/bin/bash
# Double-click to open the ledger without fetching anything.
# Use this to look at your record; use "Betting Tips" to refresh and tip.
cd "$(dirname "$0")" || exit 1
python3 -m vb report --open --no-tips >/dev/null 2>&1 \
    || python3 -m vb report --open --no-tips
