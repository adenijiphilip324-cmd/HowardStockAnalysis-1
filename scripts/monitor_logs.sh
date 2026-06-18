#!/usr/bin/env bash
set -euo pipefail

# Tail the latest pipeline and techscan logs.
echo "Tailing logs/latest.log and logs/techscan-latest.log"

# Use multitail if available, otherwise tail both in foreground
if command -v multitail >/dev/null 2>&1; then
  multitail -l "tail -n 200 -F logs/latest.log" -l "tail -n 200 -F logs/techscan-latest.log"
else
  tail -n 200 -F logs/latest.log logs/techscan-latest.log
fi
