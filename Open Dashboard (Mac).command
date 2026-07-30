#!/bin/bash
# Double-click to open the dashboard. No Python and no internet needed.
cd "$(dirname "$0")" || exit 1
open "docs/index.html"
