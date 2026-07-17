#!/usr/bin/env sh
set -eu
cd "$(dirname "$0")"
docker info >/dev/null
docker build --file Dockerfile.sandbox --tag agent-ledger-sandbox:1 .
printf '%s\n' 'Sandbox image ready: agent-ledger-sandbox:1'
printf '%s\n' 'Run: python3 sandbox_demo.py --mode hard'
