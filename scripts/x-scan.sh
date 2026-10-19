#!/usr/bin/env bash
# X scan, first part of the cloud refresh (see docs/REFRESH.md).
# Syncs main and pulls the posts taking off on X into x/.posts.json. The refresh
# session then groups them into stories (x/CLUSTERING.md) and runs x/finish.py.
# On failure data/x_trends.json is left as it was and the error is logged.
set -uo pipefail
cd "$(dirname "$0")/.."

git fetch -q origin main && git checkout -q -B main origin/main || { echo "could not sync main"; exit 1; }

python3 x/fetch.py
