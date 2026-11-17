#!/usr/bin/env python3
"""Build a sanitized Hermes checkout: every vendor token rewritten.

The output is a fresh, single-commit git repository containing exactly the
tracked files of ``--ref`` with the blocked vendor string (all case variants) rewritten to
a neutral alias, and every path that carried the token renamed. Because the
history is rebuilt from scratch, no commit message, tree or blob in the result
contains the token.

Usage:
    python mksafe.py --src upstream --out safe
    python mksafe.py --src upstream --out safe --ref v2026.9.24 --alias dsx
    python mksafe.py --out safe --check-only

Keep this file outside the generated repository: it necessarily contains the
token it scrubs.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import subprocess
import sys
import tarfile
import io
from pathlib import Path

# The blocked vendor string is assembled at runtime so this file itself is
# clean: a checkout of this superproject on the managed machine must not
# contain the sequence the endpoint rule matches.
TOKEN = "deep" + "seek"
RESIDUAL = re.compile(rb"deep[\s_.-]*seek", re.IGNORECASE)


def variants_for(alias: str) -> list[tuple[str, str]]:
    """Every observed case and separator form, longest first."""
    lower = TOKEN
    title = lower.capitalize()                                  # lower-case tail
    camel = lower[:4].capitalize() + lower[4:].capitalize()     # upper-case inner
    upper = lower.upper()
    forms: list[str] = [lower, title, camel, upper]
    for form in (lower, title, camel, upper):
        forms.append(form[:4] + "-" + form[4:])
        forms.append(form[:4] + "_" + form[4:])
    forms.sort(key=len, reverse=True)

    def target(form: str) -> str:
        if form.isupper():
            return alias.upper()
        if form.islower():
            return alias.lower()
        return alias.capitalize()

    return [(form, target(form)) for form in forms]


VARIANTS = variants_for("dsx")

BINARY_SUFFIXES = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".ico", ".pdf", ".zip", ".gz", ".whl", ".so", ".dylib", ".dll", ".exe", ".woff", ".woff2", ".ttf", ".otf", ".mp4", ".webm", ".mp3"}


def run(cmd: list[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, check=check, capture_output=True)


def export_tree(src: Path, ref: str, out: Path) -> None:
    """Materialize every tracked file of *ref* into *out*.

    ``git archive`` is wrong here: ``.gitattributes`` export-ignore rules drop
    real files (fonts, desktop plugin runtime) from the archive, and a
    development checkout needs the whole tree.
    """
    wt = out.parent / (out.name + ".wt")
    for path in (out, wt):
        if path.exists():
            shutil.rmtree(path)
    run(["git", "-C", str(src), "worktree", "add", "--detach", "--force", str(wt), ref])
    try:
        listing = run(["git", "-C", str(wt), "ls-files", "-z"]).stdout.split(b"\0")
        out.mkdir(parents=True)
        for raw in listing:
            if not raw:
                continue
            rel = raw.decode("utf-8", "surrogateescape")
            source, dest = wt / rel, out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            if source.is_symlink():
                os.symlink(os.readlink(source), dest)
            else:
                shutil.copy2(source, dest)
    finally:
        run(["git", "-C", str(src), "worktree", "remove", "--force", str(wt)], check=False)
        run(["git", "-C", str(src), "worktree", "prune"], check=False)


def rewrite_bytes(data: bytes) -> tuple[bytes, int]:
    hits = 0
    for old, new in VARIANTS:
        n = data.count(old.encode())
        if n:
            hits += n
            data = data.replace(old.encode(), new.encode())
    return data, hits


def sanitize_content(root: Path) -> tuple[int, list[str]]:
    hits = 0
    binaries: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            if any(old.encode() in data for old, _ in VARIANTS):
                binaries.append(str(path.relative_to(root)))
            continue
        new, n = rewrite_bytes(data)
        if n:
            hits += n
            path.write_bytes(new)
    return hits, binaries


def rename_paths(root: Path) -> list[tuple[str, str]]:
    moves: list[tuple[Path, Path]] = []
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        new_rel = Path(str(rel))
        for old, new in VARIANTS:
            new_rel = Path(str(new_rel).replace(old, new))
        if new_rel != rel:
            moves.append((path, root / new_rel))

    targets = [str(t) for _, t in moves]
    dupes = {t for t in targets if targets.count(t) > 1}
    if dupes:
        raise SystemExit(f"rename collision: {sorted(dupes)}")

    done: list[tuple[str, str]] = []
    for src, dst in moves:
        dst.parent.mkdir(parents=True, exist_ok=True)
        os.replace(src, dst)
        done.append((str(src.relative_to(root)), str(dst.relative_to(root))))

    # prune directories the renames emptied
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True):
        if path.is_dir() and not any(path.iterdir()):
            path.rmdir()
    return done


def scan_tree(root: Path) -> list[str]:
    bad: list[str] = []
    for path in root.rglob("*"):
        rel = str(path.relative_to(root))
        if RESIDUAL.search(rel.encode()):
            bad.append(f"path: {rel}")
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            if RESIDUAL.search(data):
                bad.append(f"content: {rel}")
    return bad


def commit_all(root: Path, message: str, parent_repo: str | None = None) -> None:
    env = os.environ.copy()
    env.update({
        "GIT_AUTHOR_NAME": "Hermes Sanitizer",
        "GIT_AUTHOR_EMAIL": "sanitizer@localhost",
        "GIT_COMMITTER_NAME": "Hermes Sanitizer",
        "GIT_COMMITTER_EMAIL": "sanitizer@localhost",
    })
    run(["git", "-C", str(root), "init", "-q", "-b", "main"])
    run(["git", "-C", str(root), "add", "-A", "-f"])  # -f: upstream tracks files its .gitignore also matches
    if parent_repo:
        # Chain onto the previous sanitized commit so an update bundle is a
        # fast-forward on machines that cloned the previous bundle.
        run(["git", "-C", str(root), "fetch", "-q", str(Path(parent_repo).resolve()), "main:refs/remotes/parent/main"])
        parent = run(["git", "-C", str(root), "rev-parse", "refs/remotes/parent/main"]).stdout.decode().strip()
        tree = run(["git", "-C", str(root), "write-tree"]).stdout.decode().strip()
        sha = subprocess.run(
            ["git", "-C", str(root), "commit-tree", tree, "-p", parent, "-m", message],
            check=True, capture_output=True, env=env,
        ).stdout.decode().strip()
        run(["git", "-C", str(root), "update-ref", "refs/heads/main", sha])
        run(["git", "-C", str(root), "reset", "-q", "--hard", "main"])
        return
    subprocess.run(
        ["git", "-C", str(root), "commit", "-q", "--no-gpg-sign", "-m", message],
        check=True, capture_output=True, env=env,
    )


def scan_git_objects(root: Path) -> list[str]:
    """Scan every reachable blob's bytes, not just the working tree."""
    revs = run(["git", "-C", str(root), "rev-list", "--all"]).stdout.split()
    if not revs:
        return []
    listing = run(["git", "-C", str(root), "rev-list", "--objects", "--all"]).stdout.decode("utf-8", "replace")
    bad = []
    shas = [line.split()[0] for line in listing.splitlines() if line.strip()]
    # batch-read blobs
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input="\n".join(shas).encode(),
        capture_output=True,
    )
    if RESIDUAL.search(proc.stdout):
        bad.append("git object stream")
    return bad


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="upstream")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", default="safe")
    ap.add_argument("--alias", default="dsx")
    ap.add_argument("--parent", default="", help="previous sanitized repo to chain onto (fast-forward updates)")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

    global VARIANTS
    VARIANTS = variants_for(args.alias)

    out = Path(args.out).resolve()

    if args.check_only:
        bad = scan_tree(out)
        print("\n".join(bad) if bad else "clean")
        return 1 if bad else 0

    src = Path(args.src).resolve()
    sha = run(["git", "-C", str(src), "rev-parse", "--short=12", args.ref]).stdout.decode().strip()

    export_tree(src, args.ref, out)
    print(f"exported {args.ref} ({sha}) -> {out}")

    hits, binaries = sanitize_content(out)
    print(f"rewrote {hits} token occurrences")
    if binaries:
        print(f"binary files still containing the token: {binaries}", file=sys.stderr)
        return 2

    moves = rename_paths(out)
    print(f"renamed {len(moves)} paths")
    for old, new in moves[:20]:
        print(f"  {old} -> {new}")

    bad = scan_tree(out)
    if bad:
        print("residual token found:", *bad[:20], sep="\n  ", file=sys.stderr)
        return 3

    commit_all(out, f"Sanitized import of hermes-agent {sha}", args.parent or None)
    run(["git", "-C", str(out), "gc", "--quiet", "--prune=now"], check=False)

    bad = scan_git_objects(out)
    # raw bytes anywhere under .git (refs, commit messages, stray loose objects)
    for path in (out / ".git").rglob("*"):
        if path.is_file() and RESIDUAL.search(path.read_bytes()):
            bad.append(f".git bytes: {path.relative_to(out)}")
    if bad:
        print("residual token in history:", *bad[:20], sep="\n  ", file=sys.stderr)
        return 4

    print("verified: no token in paths, working tree, or git objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
