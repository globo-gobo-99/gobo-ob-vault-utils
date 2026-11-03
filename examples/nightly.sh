#!/usr/bin/env bash
set -euo pipefail
umask 077
if [[ $# -lt 3 || $# -gt 4 ]]; then
  printf '%s\n' 'Usage: nightly.sh VAULT SYNC_LOG PRIVATE_CHECKPOINT [TIMEZONE]' >&2
  exit 2
fi
script_root=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
exec python3 "$script_root/vault_maintenance.py" run --apply \
  --vault "$1" --sync-log "$2" --checkpoint "$3" --timezone "${4:-America/Boise}"
