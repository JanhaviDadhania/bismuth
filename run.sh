#!/bin/bash
# Start bismuth v2. Ctrl+C stops it.
#
# The memory git loop lives inside the runtime now (v2/gitsync.py), so this
# script does not run one — a second syncer would race the first.
set -e
DIR="$(cd "$(dirname "$0")" && pwd)"

python3 -m v2 check || {
  echo
  echo "Preflight failed — fix the above, then run again."
  exit 1
}

cd "$DIR"
exec python3 -m v2 serve
