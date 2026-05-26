#!/usr/bin/env bash
set -euo pipefail

# Run the technical scanner and write to a timestamped log with latest symlink
mkdir -p logs
LOGFILE=logs/techscan-$(date +%F_%H%M%S).log
ln -sf "$LOGFILE" logs/techscan-latest.log
echo "Starting technical scanner at $(date)" | tee -a "$LOGFILE"
python3 backend/technical_scanner.py 2>&1 | tee -a "$LOGFILE"
echo "Technical scanner finished at $(date)" | tee -a "$LOGFILE"
