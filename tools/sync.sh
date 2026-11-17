#!/usr/bin/env bash
# One-shot sync: pristine upstream -> sanitized mirror -> fork -> submodule.
#
#   tools/sync.sh            # update upstream, rebuild, publish, bump gitlink
#   tools/sync.sh --dry-run  # fetch and report only, mutate nothing
#
# The superproject pins `upstream` (pristine, update=none for clones) and
# `hermes` (the sanitized fork). Only the sanitized history is ever published.
set -euo pipefail
cd "$(dirname "$0")/.."

DRY=0
[ "${1:-}" = "--dry-run" ] && DRY=1

say() { printf '\n== %s ==\n' "$1"; }

say "upstream"
git -C upstream fetch -q origin main
UP=$(git -C upstream rev-parse --short HEAD)
NEW=$(git -C upstream rev-parse --short origin/main)
echo "checked out $UP, origin/main $NEW"

if [ "$DRY" = 1 ]; then
    if [ "$UP" = "$NEW" ]; then echo "upstream is current"; else echo "upstream would move $UP -> $NEW"; fi
    echo "dry run: would rebuild safe/, push main+sanitized, bump hermes/"
    exit 0
fi

if [ "$UP" = "$NEW" ] && [ "$(git -C safe rev-parse HEAD 2>/dev/null)" = "$(git -C hermes rev-parse HEAD)" ]; then
    echo "already in sync, nothing to do"
    exit 0
fi

say "fast-forward upstream"
git submodule update --remote --checkout upstream
UP=$(git -C upstream rev-parse --short HEAD)

say "rebuild"
tools/release.sh

say "publish"
git -C safe push origin main:refs/heads/main
git -C safe push origin main:refs/heads/sanitized
echo "fork now at $(git -C safe rev-parse --short HEAD)"

say "submodule"
git submodule update --remote --checkout hermes
git add hermes
if git diff --cached --quiet; then
    echo "hermes/ already current"
else
    git commit -q -m "sync: hermes $(git -C hermes rev-parse --short HEAD) (upstream $UP)"
    echo "committed gitlink bump"
fi

git submodule status
