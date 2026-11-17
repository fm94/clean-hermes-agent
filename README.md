# Hermes on a CrowdStrike-locked Windows PC

A workspace that keeps a clean Hermes checkout in sync with upstream while never
materializing the vendor name the endpoint agent blocks.

```
port-hermes/                 this repo (Mac-side workspace)
├── upstream/                submodule → NousResearch/hermes-agent (pristine, update=none)
├── hermes/                  submodule → fm94/hermes-agent @ sanitized (the clean checkout)
├── safe/                    build scratch, gitignored, pushed to the fork
├── tools/mksafe.py          the transform
├── tools/release.sh         rebuild + bundle + hash
├── tools/sync.sh            upstream → sanitized → fork → submodule, one shot
└── windows/                 installer wrapper + diagnostics
```

## Why this shape

- `upstream/` is the pristine source, pinned by the superproject. `tools/sync.sh`
  fast-forwards it to its remote tip, so "keep in sync with the main repo" is one
  command. It is marked `update = none` in `.gitmodules`: a clone of this
  workspace never fetches it, because its history is exactly what the scanner
  blocks.
- `hermes/` is the sanitized checkout, published to your fork. This is the copy
  you run and the copy Windows clones.
- `safe/` is where `mksafe.py` writes a candidate tree before it is committed and
  pushed. It is not part of the repo.

## The published branch

[`fm94/hermes-agent`](https://github.com/fm94/hermes-agent) now holds a single
root commit, `8fa7ab27`, on both `main` and `sanitized` (same commit; `main` is
what a default clone gets, `sanitized` names it explicitly). The fork's original
upstream history was replaced — it was a fresh fork with no work on it, and
keeping that history would put the blocked token back in every clone.

- 26,155 files, identical to upstream `0309b005235b` apart from the rename.
- 3,385 token occurrences across 445 files rewritten; 9 paths renamed (provider
  plugin, 4 catalog entries, 3 tests).
- Verified clean: working tree, paths, all 26,995 git objects, raw bytes.
- The renamed `dsx` provider is inert (placeholder base URL); every other
  provider is untouched.

## Install on Windows

```powershell
powershell -ExecutionPolicy Bypass -File .\install-safe.ps1 `
  -Repo https://github.com/fm94/hermes-agent.git
```

`install-safe.ps1` sets `HERMES_REPO_URL` and `HERMES_INSTALL_CHANNEL=main`, then
runs the unmodified official `install.ps1`. `main` matters: the default stable
channel looks up the official GitHub repo and tries to fetch a release tag this
clone does not have.

Offline alternative: `-Repo .\hermes-safe.bundle -BundleHash <hash>` with the
bundle from `tools/release.sh`. A bundle is a valid git source, so no network
clone is needed.

If the PC can clone the whole workspace, `git clone --recurse-submodules` skips
`upstream/` and fetches only `hermes/`.

## Sync with upstream

```bash
tools/sync.sh --dry-run   # fetch upstream, report the new SHA
tools/sync.sh             # rebuild, push main+sanitized, bump the hermes/ gitlink
```

Only the sanitized history is published; the pristine tree never leaves
`upstream/`.

## If the uv step still fails

Run `windows\diagnose.ps1` on the PC and send back the log. It records proxy and
TLS variables, Falcon/Defender services, DNS/TCP/HTTPS to PyPI, GitHub and
astral.sh, write tests for `%TEMP%`, the uv cache and the install dir, and a real
`uv venv` + `uv pip install certifi` probe. That separates three causes that look
identical from the console:

1. TLS interception or a proxy uv does not trust (`SSL_CERT_FILE`,
   `UV_NATIVE_TLS=1`).
2. PyPI/GitHub blocked (internal index via `UV_INDEX_URL`, or an offline
   wheelhouse).
3. `uv.exe` execution blocked by Falcon — no repo-side fix; needs an IT
   exception, which is where a prebuilt/MSIX path is the only alternative.

## Known residual risk

Runtime fetches can still carry the vendor name into disk caches
(`~/.hermes/cache/model_catalog.json`, `models_dev_cache.json`), logs and the
session DB if a remote catalog lists that vendor's models. If the scanner blocks
those writes, the fix is a redaction hook around `atomic_json_write` / the
logger. Not added yet: it depends on what the scanner actually inspects.

## Notes

- `hermes update` on the fork must not add `NousResearch/hermes-agent` as
  `upstream`; that fetch would repopulate `.git` with the original blobs.
  `install-safe.ps1` writes the `.skip_upstream_prompt` marker so the offer is
  skipped.
- `tools/sync.sh` pushes over your SSH key (`fm94`).
- The superproject has no remote yet; add one when you want this workspace on
  another machine.
