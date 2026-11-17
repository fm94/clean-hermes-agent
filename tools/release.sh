#!/usr/bin/env bash
# Rebuild the sanitized mirror, then emit a transferable bundle + checksum.
#
#   tools/release.sh           # rebuild from upstream HEAD, chained onto ./safe
#   tools/release.sh --fresh   # start a new root commit (breaks fast-forward updates)
#
# Chaining matters: the Windows clone follows `main`, so each release must be a
# fast-forward of the previous one or `hermes update` / `git pull` stops working.
set -euo pipefail
cd "$(dirname "$0")/.."

ARGS=()
PARENT=()
for arg in "$@"; do
    case "$arg" in
        --fresh) ;;
        *) ARGS+=("$arg") ;;
    esac
done
if [ -d safe ] && [[ ! " $* " =~ " --fresh " ]]; then
    PARENT=(--parent safe)
fi

python3 tools/mksafe.py --src upstream --out safe-next "${PARENT[@]}" ${ARGS[@]+"${ARGS[@]}"}

ORIGIN=$(git -C safe remote get-url origin 2>/dev/null || true)

rm -rf safe.prev
[ -d safe ] && mv safe safe.prev
mv safe-next safe
[ -n "$ORIGIN" ] && git -C safe remote add origin "$ORIGIN"

rm -f hermes-safe.bundle
git -C safe bundle create ../hermes-safe.bundle --all
shasum -a 256 hermes-safe.bundle > hermes-safe.bundle.sha256

echo
echo "commit : $(git -C safe rev-parse --short HEAD)"
echo "files  : $(git -C safe ls-files | wc -l | tr -d ' ')"
echo "bundle : $(du -h hermes-safe.bundle | cut -f1)"
cat hermes-safe.bundle.sha256
