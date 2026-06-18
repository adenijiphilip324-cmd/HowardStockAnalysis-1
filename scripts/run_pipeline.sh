#!/usr/bin/env bash
set -euo pipefail

# Creates a timestamped log and runs the full pipeline, keeping a latest symlink.
mkdir -p logs
LOGFILE=logs/pipeline-$(date +%F_%H%M%S).log
ln -sf "$LOGFILE" logs/latest.log
echo "Starting pipeline at $(date)" | tee -a "$LOGFILE"
python3 backend/main.py 2>&1 | tee -a "$LOGFILE"
echo "Pipeline finished at $(date)" | tee -a "$LOGFILE"
