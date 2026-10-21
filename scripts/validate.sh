#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
python scripts/validate_static.py
