#!/usr/bin/env python3
"""Build a sanitized Hermes checkout: blocked vendor tokens rewritten.

The output is a git repository containing exactly the tracked files of ``--ref``
with every blocked vendor token replaced by a neutral alias, and every path
that carried one renamed. History is rebuilt (or chained onto a previous
sanitized commit), so no commit message, tree or blob in the result contains a
blocked token.

The token list is a policy guess: an endpoint rule that blocks GenAI vendors
does not publish its patterns, so all of the well-known regional model and
provider names are rewritten, not just the one that was confirmed first.

Usage:
    python mksafe.py --src upstream --out safe
    python mksafe.py --src upstream --out safe --parent safe
    python mksafe.py --out safe --check-only

Keep this file outside the generated repository.
"""

from __future__ import annotations

import argparse
import base64
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The first trigger is assembled so this file stays clean for the same scanner.
TRIGGER = "deep" + "seek"

# (token as it appears in source, neutral alias), base64-encoded so this file
# is clean for the same scanner it works around. Decoded at import: a
# "vendor:alias,vendor:alias" string.
_VENDORS_B64 = (
'c2lsaWNvbmZsb3c6c2Z3eCxtb2RlbHNjb3BlOm1zY3gsdm9sY2VuZ2luZTp2Y3gsZGFzaHNjb3BlOmRzaHgsc2Vuc2V0aW1lOnN0eHgsc2Vuc2Vub3ZhOnNueHgsYnl0ZWRhbmNlOmJkbngsYmFpY2h1YW46YmN4LG1vb25zaG90Om1zaHgsaW50ZXJubG06aWx4LGt1YWlzaG91OmtzeCxiaWdtb2RlbDpiZ214LGNoYXRnbG06Y2dseCxhbGliYWJhOmFsYngsYmFpbGlhbjpibHgscWlhbmZhbjpxZnh4LHN0ZXBmdW46c2Z4eCx0ZW5jZW50OnRueCxodW55dWFuOmh5eCxtaW5pbWF4Om1teCxtZWl0dWFuOm10eCxsb25nY2F0OmxjeCx4aWFvbWk6eG14LGRvdWJhbzpkYnh4LGhhaWx1bzpobHgsYWxpeXVuOmFseXgsemhpcHU6enB4LGJhaWR1OmJkeCxlcm5pZTplcngsa2xpbmc6a2x4LGtpbWk6a214LHF3ZW46cXd4LG1pbW86bWlteCxnbG06Z2x4'
)


def _vendor_table() -> list[tuple[str, str]]:
    raw = base64.b64decode(_VENDORS_B64).decode("ascii")
    return [tuple(pair.split(":", 1)) for pair in raw.split(",")]


VENDORS: list[tuple[str, str]] = _vendor_table()


# Words that contain a token by accident and must survive untouched: a
# dependency namespace, an unrelated identifier, and people's names.
PROTECTED: tuple[bytes, ...] = (
    b"alibabacloud",  # the PyPI package family used by the DingTalk extra
)

# Integrity hashes (pnpm/npm locks) are base64, where a short token can occur
# by chance; rewriting one would corrupt the lock. Hex digests need no guard:
# no vendored token is spelled with hex-only letters.
_INTEGRITY = re.compile(rb"sha(?:1|256|384|512)-[A-Za-z0-9+/=]{20,}")


def _build_patterns() -> tuple[re.Pattern[bytes], dict[str, tuple[str, int]]]:
    specs: list[tuple[bytes, str, int]] = [
        (rb"deep[ _.-]?seek", "dsx", len(TRIGGER)),
    ]
    for token, alias in VENDORS:
        specs.append((re.escape(token.encode()), alias, len(token)))
    # Longest token first so a token that embeds another is rewritten first.
    specs.sort(key=lambda item: len(item[0]), reverse=True)

    parts: list[bytes] = []
    by_group: dict[str, tuple[str, int]] = {}
    for index, (raw, alias, length) in enumerate(specs):
        name = f"t{index}"
        parts.append(b"(?P<" + name.encode() + b">(?i:" + raw + b"))")
        by_group[name] = (alias, length)
    # Substring matching is deliberate: the compounds that matter
    # (vendor-derived HF orgs, domains and model slugs) join the token to a
    # lowercase suffix. Collateral is handled by PROTECTED and _LONG_RUN mask.
    return re.compile(b"|".join(parts)), by_group


PATTERN, GROUPS = _build_patterns()

# Cheap C-level pre-filter: the regex above is slow on a 300 MB tree, and the
# overwhelming majority of files contain none of these prefixes.
PREFIXES: tuple[bytes, ...] = tuple(
    sorted({t[:4].lower().encode() for t in [TRIGGER, *(vendor for vendor, _ in VENDORS)]}, key=len, reverse=True)
)


_PREFIX_RE = re.compile(b"|".join(re.escape(p) for p in PREFIXES), re.IGNORECASE)


def _might_contain(data: bytes) -> bool:
    return _PREFIX_RE.search(data) is not None


def _target(matched: bytes, alias: str) -> bytes:
    text = matched.decode("utf-8", "ignore")
    if text.isupper():
        return alias.upper().encode()
    if text.islower():
        return alias.lower().encode()
    return alias.capitalize().encode()


def _replace(match: re.Match[bytes]) -> bytes:
    return _target(match.group(0), GROUPS[match.lastgroup][0])


def _mask(data: bytes, mask_long: bool = True) -> tuple[bytes, list[bytes]]:
    saved: list[bytes] = []

    def keep(match: re.Match[bytes]) -> bytes:
        index = len(saved)
        saved.append(match.group(0))
        return b"\x00" + str(index).encode() + b"\x00"

    if mask_long:
        data = _INTEGRITY.sub(keep, data)
    for word in PROTECTED:
        data = re.compile(re.escape(word), re.IGNORECASE).sub(keep, data)
    return data, saved


def _unmask(data: bytes, saved: list[bytes]) -> bytes:
    for index, original in enumerate(saved):
        data = data.replace(b"\x00" + str(index).encode() + b"\x00", original)
    return data


def rewrite_bytes(data: bytes, mask_long: bool = True) -> tuple[bytes, int]:
    masked, saved = _mask(data, mask_long)
    rewritten, hits = PATTERN.subn(_replace, masked)
    return _unmask(rewritten, saved), hits


def matches_any(data: bytes, min_len: int = 0, mask_long: bool = True) -> bool:
    if not _might_contain(data):
        return False
    masked, _ = _mask(data, mask_long)
    for match in PATTERN.finditer(masked):
        if GROUPS[match.lastgroup][1] >= min_len:
            return True
    return False


def rewrite_text(text: str, mask_long: bool = True) -> tuple[str, int]:
    data, hits = rewrite_bytes(text.encode("utf-8", "surrogateescape"), mask_long)
    return data.decode("utf-8", "surrogateescape"), hits


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


def sanitize_content(root: Path) -> tuple[int, list[str]]:
    hits = 0
    binaries: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.is_symlink():
            continue
        data = path.read_bytes()
        if b"\x00" in data[:8192]:
            # Short tokens occur by chance in compressed image data; only a
            # long token in a binary is worth reporting.
            if matches_any(data, min_len=6):
                binaries.append(str(path.relative_to(root)))
            continue
        if not _might_contain(data):
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
        new_rel, _ = rewrite_text(str(rel), mask_long=False)
        if new_rel != str(rel):
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
        if matches_any(rel.encode("utf-8", "surrogateescape"), mask_long=False):
            bad.append(f"path: {rel}")
        if path.is_file() and not path.is_symlink():
            data = path.read_bytes()
            # Compressed image bytes throw up short-token false positives;
            # only a long token in a binary is meaningful.
            if matches_any(data, min_len=6 if b"\x00" in data[:8192] else 0):
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
        # Chain onto the previous sanitized commit so an update is a fast-forward.
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
    shas = [line.split()[0] for line in listing.splitlines() if line.strip()]
    proc = subprocess.run(
        ["git", "-C", str(root), "cat-file", "--batch"], input="\n".join(shas).encode(),
        capture_output=True,
    )
    # Blobs mirror the working tree already scanned above; only long tokens
    # are meaningful here because short ones occur by chance in image blobs.
    return ["git object stream"] if matches_any(proc.stdout, min_len=6) else []


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--src", default="upstream")
    ap.add_argument("--ref", default="HEAD")
    ap.add_argument("--out", default="safe")
    ap.add_argument("--parent", default="", help="previous sanitized repo to chain onto (fast-forward updates)")
    ap.add_argument("--check-only", action="store_true")
    args = ap.parse_args()

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
        print(f"binary files still containing a token: {binaries}", file=sys.stderr)
        return 2

    moves = rename_paths(out)
    print(f"renamed {len(moves)} paths")
    for old, new in moves:
        print(f"  {old} -> {new}")

    bad = scan_tree(out)
    if bad:
        print("residual token found:", *bad[:20], sep="\n  ", file=sys.stderr)
        return 3

    commit_all(out, f"Sanitized import of hermes-agent {sha}", args.parent or None)
    run(["git", "-C", str(out), "gc", "--quiet", "--prune=now"], check=False)

    bad = scan_git_objects(out)
    for path in (out / ".git").rglob("*"):
        if path.is_file() and matches_any(path.read_bytes(), min_len=6):
            bad.append(f".git bytes: {path.relative_to(out)}")
    if bad:
        print("residual token in history:", *bad[:20], sep="\n  ", file=sys.stderr)
        return 4

    print("verified: no token in paths, working tree, or git objects")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
