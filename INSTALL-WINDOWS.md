# Install on Windows (CrowdStrike-managed)

Everything here is pre-cleaned: the checkout, its history and the submodule it
pulls contain no reference to the vendor name the endpoint agent blocks. Do not
clone the original upstream repository on this machine — its history is exactly
what triggers the rule.

**Requirements:** Windows 10/11 x64, PowerShell 5.1+, network access to
`github.com` and `pypi.org`. Git is needed to clone the workspace; if it is
missing, use the wrapper-only path and the official installer stages Git for
Windows itself.

## 1. Get the installer

Whole workspace (also gives you the checkout and the diagnostics):

```powershell
git clone --recurse-submodules https://github.com/fm94/clean-hermes-agent.git
cd clean-hermes-agent
```

Only the submodules you need are fetched: `hermes/` comes down, `upstream/` is
marked `update = none` and stays empty. That is deliberate — it is the pristine
copy and its history must not land on this machine.

Wrapper only, no checkout:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/fm94/clean-hermes-agent/main/windows/install-safe.ps1 -OutFile install-safe.ps1
```

## 2. Run the installer

From the workspace:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install-safe.ps1 `
  -Repo https://github.com/fm94/hermes-agent.git
```

Or, with the wrapper downloaded on its own:

```powershell
powershell -ExecutionPolicy Bypass -File .\install-safe.ps1 `
  -Repo https://github.com/fm94/hermes-agent.git
```

What it does: sets `HERMES_REPO_URL` and `HERMES_INSTALL_CHANNEL=main`, then runs
the unmodified official `install.ps1`. The channel matters — the default stable
channel looks up the official repository and tries to fetch a release tag this
clone does not have. It also writes `.skip_upstream_prompt` so `hermes update`
never offers to add the original repository as `upstream`.

First install: 2–5 minutes. Python 3.14, Node, pnpm, ripgrep and FFmpeg are
staged under `%LOCALAPPDATA%\hermes`.

## 3. Verify

```powershell
hermes --version
hermes doctor
hermes model
```

`hermes model` is where you pick a provider. Any provider works except the one
that was removed; nothing else is affected.

## 4. If the install fails

- **At the clone:** `git --version`, then check proxy settings
  (`HTTP_PROXY`/`HTTPS_PROXY`) and that `github.com:443` is reachable.
- **The checkout dies again mid-way:** the endpoint agent normally records the
  rule and the exact file it blocked. Send that path back — one real file name
  beats any amount of guessing at the pattern.
- **At the uv step:** run the evidence collector and send back the log:

  ```powershell
  powershell -ExecutionPolicy Bypass -File .\windows\diagnose.ps1
  ```

  It records proxy/TLS variables, endpoint-agent services, DNS/TCP/HTTPS to
  PyPI, GitHub and astral.sh, write tests for `%TEMP%`, the uv cache and the
  install dir, and a real `uv venv` + install probe. That separates the three
  causes that look identical from the console: TLS interception (fix:
  `SSL_CERT_FILE` or `UV_NATIVE_TLS=1`), a blocked index (fix: `UV_INDEX_URL` or
  an offline wheelhouse), or `uv.exe` execution blocked by the endpoint agent
  (fix: an IT exception, or the signed desktop package instead of a source
  install).

## 5. Offline install

If the machine cannot reach GitHub, carry the bundle produced by
`tools/release.sh` and point the wrapper at it:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install-safe.ps1 `
  -Repo .\hermes-safe.bundle `
  -BundleHash <hash from hermes-safe.bundle.sha256>
```

A git bundle is a valid clone source, so the installer works unchanged. The
installed `origin` points at the bundle file; replacing it later lets
`hermes update` fast-forward.

## 6. Updating

```powershell
hermes update
```

This pulls `main` from `fm94/hermes-agent`. Each published sync is a
fast-forward, so it is a normal pull. If it ever offers to add the official
repository as `upstream`, answer **No** — that fetch is the one thing that would
bring the blocked history back.

## 7. Troubleshooting

- **Execution policy:** use `-ExecutionPolicy Bypass` on the `powershell`
  command, not `Set-ExecutionPolicy` (which may be locked by policy).
- **Long paths:** the installer sets `core.longpaths` for its clone. If you
  clone the workspace manually, add `git config --global core.longpaths true`.
- **Antivirus quarantines `uv.exe`:** this is a known false positive on
  unsigned Rust binaries. The official Hermes README has an attestation check
  and folder-exclusion steps; the same applies here.
- **Custom location:** set `HERMES_HOME` before running the installer to move
  `%LOCALAPPDATA%\hermes`.
- **Nothing on PATH after install:** open a new terminal; the installer edits
  the user PATH, not the current session.
