#!/bin/bash
# Weekly TFRRS data refresh. Invoked by launchd; safe to run by hand too.
cd "$(dirname "$0")" || exit 1
source venv/bin/activate
echo "[$(date '+%Y-%m-%d %H:%M:%S')] starting refresh" >> data/update.log
python scrape.py --refresh >> data/update.log 2>&1
echo "[$(date '+%Y-%m-%d %H:%M:%S')] refresh done (exit $?)" >> data/update.log
