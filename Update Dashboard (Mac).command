#!/bin/bash
# Double-click to fetch the newest WDFW reports and rebuild the dashboard.
# Everything this does lives in run.py, so the button and the command line
# behave identically.
cd "$(dirname "$0")" || exit 1
for py in python3 python; do
  if command -v "$py" >/dev/null 2>&1; then exec "$py" run.py --update; fi
done
echo
echo "  Python was not found on this Mac."
echo "  Install it from https://www.python.org/downloads/ and try again,"
echo "  or just double-click 'Open Dashboard (Mac).command' to view the"
echo "  data already in this folder without updating it."
echo
read -r -p "Press return to close. "
