# Install on Windows (CrowdStrike-managed)

One clone, no submodules. The repository itself is the Hermes checkout; it
carries no blocked vendor name and no bundled provider, so you add your own
endpoint afterwards.

**Requirements:** Windows 10/11 x64, PowerShell 5.1+, network access to
`github.com` and `pypi.org`. Git is needed to clone; if it is missing, download
only the wrapper and the official installer stages Git for Windows itself.

## 1. Clone

```powershell
git clone https://github.com/fm94/clean-hermes-agent.git
cd clean-hermes-agent
```

That is the whole product: Hermes at the repository root, with `windows\` added.
No submodules, no second fetch, no upstream history on the machine.

Wrapper only, no checkout:

```powershell
Invoke-WebRequest https://raw.githubusercontent.com/fm94/clean-hermes-agent/main/windows/install-safe.ps1 -OutFile install-safe.ps1
```

## 2. Run the installer

From the clone:

```powershell
powershell -ExecutionPolicy Bypass -File .\windows\install-safe.ps1 `
  -Repo https://github.com/fm94/clean-hermes-agent.git
```

`install-safe.ps1` sets `HERMES_REPO_URL` and `HERMES_INSTALL_CHANNEL=main`, then
runs the unmodified official `install.ps1`, which clones this repository into
`%LOCALAPPDATA%\hermes\hermes-agent` and creates the `hermes` launcher.

First install: 2–5 minutes. Python 3.14, Node, pnpm, ripgrep and FFmpeg are
staged under `%LOCALAPPDATA%\hermes`.

## 3. Point it at your endpoint

```powershell
hermes --version
hermes doctor
hermes model
```

There are no bundled providers — the picker offers `custom` and nothing else.
Give it a base URL and key, or add an entry under `providers:` in
`%LOCALAPPDATA%\hermes\config.yaml`:

```yaml
providers:
  mine:
    type: openai
    base_url: https://your-endpoint/v1
    api_key_env: MINE_API_KEY
```

Then `hermes model` should list `mine`.

## 4. If the install fails

- **At the clone:** `git --version`, then check proxy settings
  (`HTTP_PROXY`/`HTTPS_PROXY`) and that `github.com:443` is reachable.
- **The checkout dies mid-way:** the endpoint agent normally records the rule
  and the exact file it blocked. Send that path back — one real file name beats
  any amount of guessing.
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

## 5. Updating

`hermes update` pulls from the same repository; each published build is a
fast-forward. If it offers to add the original upstream, answer **No**.

## 6. Troubleshooting

- **Execution policy:** use `-ExecutionPolicy Bypass` on the `powershell`
  command, not `Set-ExecutionPolicy` (which may be locked by policy).
- **Long paths:** the installer sets `core.longpaths` for its clone. If you
  clone manually, add `git config --global core.longpaths true`.
- **Antivirus quarantines `uv.exe`:** a known false positive on unsigned Rust
  binaries. The official Hermes README has an attestation check and
  folder-exclusion steps; the same applies here.
- **Custom location:** set `HERMES_HOME` before running the installer to move
  `%LOCALAPPDATA%\hermes`.
- **Nothing on PATH after install:** open a new terminal; the installer edits
  the user PATH, not the current session.
