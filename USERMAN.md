# MATLAB MCP Server — User Manual

A short guide to running and using the MATLAB MCP server. Architecture and internals live in `README.md`; this file covers **what to do as a user**.

---

## 1. What it is

An MCP (Model Context Protocol) server that lets an AI agent (Hermes, Claude Desktop, …) drive **MATLAB batch mode** over stdio. It exposes 7 tools: execute code, run scripts, move files in/out of a sandbox directory, and query MATLAB info.

Every `matlab_execute` call spawns a **fresh MATLAB process** (≈10–15 s startup, R2024a). There is no persistent workspace between calls — see §6 for the practical consequences.

## 2. Requirements

| Component | Requirement |
|---|---|
| MATLAB | R2020a+ with a valid license, on PATH or via full path in config |
| Python | 3.10+ (server runtime) |
| Dependencies | `fastmcp>=2.0.0`, `pyyaml>=6.0` (auto-installed with the wheel) |

## 3. Installation

**From the wheel** (recommended):

```bat
C:\Users\MATTIA\source\hermes-dir\.venv\Scripts\pip.exe install C:\Users\MATTIA\source\hermes-dir\matlab-mcp-server\dist\matlab_mcp_server-0.1.0-py3-none-any.whl
```

This installs a console script `matlab-mcp-server` into the venv's `Scripts` directory.

**From source** (development):

```bat
cd C:\Users\MATTIA\source\hermes-dir\matlab-mcp-server
C:\Users\MATTIA\source\hermes-dir\.venv\Scripts\pip.exe install -e .
```

**Verify:**

```bat
C:\Users\MATTIA\source\hermes-dir\.venv\Scripts\matlab-mcp-server.exe --help
```

## 4. Configuration

The server reads `config.yaml` (project root). The two fields that matter:

```yaml
matlab:
  executable: C:/Program Files/MATLAB/R2024a/bin/matlab   # full path (spaces OK)
  default_timeout_s: 300                                  # max seconds per call

paths:
  sandbox_dir: C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/matlab-sandbox
```

- **`sandbox_dir`** — the only directory MATLAB and the file tools can touch. It is created automatically at startup. Use forward slashes in paths.
- If no config file is found, the server falls back to built-in defaults (`matlab` from PATH, sandbox in the temp dir) and logs a warning — always pass `--config` in production.

Start manually (for testing):

```bat
matlab-mcp-server --config C:\Users\MATTIA\source\hermes-dir\matlab-mcp-server\config.yaml
```

## 5. Connecting to Hermes

Add to the MCP connectors config. **Two rules that matter:**

1. `args` must be a **JSON array of strings**, not one string (a string fails with `ValidationError: StdioServerParameters`).
2. Use the **absolute path** to the console script for `command` — the Hermes desktop app's PATH usually doesn't include the venv.

```json
"matlab-mcp-unofficial": {
  "command": "C:\\Users\\MATTIA\\source\\hermes-dir\\.venv\\Scripts\\matlab-mcp-server.exe",
  "args": ["--config", "C:\\Users\\MATTIA\\source\\hermes-dir\\matlab-mcp-server\\config.yaml"],
  "transport": "stdio"
}
```

After saving, request a reconnect. A healthy connection logs: `registered 7 tool(s): mcp__matlab_mcp_unofficial__matlab_execute, …` (plus FastMCP's built-in `list_resources`/`read_resource`/`list_prompts` stubs — harmless).

## 6. The 7 tools

### Execute

| Tool | Arguments | What it does |
|---|---|---|
| `matlab_execute` | `code: str`, `timeout_s: int = 300` | Runs MATLAB code in a fresh process. Returns JSON: `exit_code`, `stdout`, `stderr`, optional `matlab_error`. |
| `matlab_run_script` | `script_path: str`, `output_vars: list[str] = None` | Runs a `.m` file from the sandbox; optionally saves named variables as `.mat` files (then reports and deletes them). |

Example call (note the **single quotes** — see §7):

```
matlab_execute(code="x = 1:5; disp(sum(x));")
→ {"exit_code": 0, "stdout": "15", ...}
```

### Files (sandbox in/out, base64-encoded, 100 MB cap)

| Tool | Arguments | What it does |
|---|---|---|
| `matlab_upload_file` | `content_base64: str`, `filename: str` | Writes a file into the sandbox. |
| `matlab_download_file` | `filename: str` | Returns `filename=…`, `size_bytes=…`, `base64_content=…`. |
| `matlab_list_files` | `pattern: str = "*"` | Lists sandbox files with sizes (glob filter). |

Typical flow: upload `data.csv` → `matlab_execute(code="d = csvread('data.csv'); ...")` → `matlab_download_file(filename="result.csv")`.

### Info

| Tool | Arguments | What it does |
|---|---|---|
| `matlab_info` | — | Version, platform, `matlabroot`. Good first call to verify the installation. |
| `matlab_diagnose` | `toolboxes: list[str] = None` | Checks toolbox availability (a fixed common set if omitted). |

## 7. Rules of thumb

1. **Single quotes for MATLAB strings.** `save('out.mat','x')` works; `save("out.mat","x")` fails with `Unable to resolve the name 'out.mat'`. (Double quotes are string *arrays* in modern MATLAB, not classic char strings.)
2. **Batch your work into one call.** Each call pays the ~10–15 s MATLAB startup. `load('d.mat'); process; save('o.mat','result');` in a single `matlab_execute` beats three separate calls.
3. **Nothing persists between calls.** No variables, no paths, no loaded functions survive to the next call. Re-`load`/`addpath` every time, or save intermediate state to `.mat`/`.csv` files in the sandbox.
4. **Capture output with `disp`/`fprintf`.** Unterminalized statements (trailing `;`) produce no `stdout`.
5. **MAT files are opaque to the server.** `matlab_download_file` returns raw `.mat` bytes — decode them with Python `scipy.io.loadmat` (or MATLAB) on the client side.
6. **Errors are structured, not fatal.** A MATLAB error returns `exit_code: 1` with `matlab_error` in the JSON; the server keeps running.

## 8. Troubleshooting

| Symptom | Cause / fix |
|---|---|
| `ValidationError: 1 validation error for StdioServerParameters` at connect | `args` is a string, not an array — §5. |
| Connect fails, "command not found" / spawn error | `command` isn't an absolute path to the `.exe` — §5. |
| `Unable to resolve the name '<file>'` in `matlab_error` | Double quotes around a MATLAB string — §7.1. |
| `matlab_error: … not found` for `save`/`load` | Sandbox dir missing or wrong `paths.sandbox_dir` — check it exists and is writable. |
| `timeout: true` in the result | Call exceeded `timeout_s`; raise it in config or split the work. |
| Server registered 0 tools / MATLAB silent | `matlab` binary not found — use the full `executable` path; verify with `matlab_info`. |
| Long calls feel slow | Expected: one MATLAB process per call — batch (§7.2). |

## 9. Quick self-test

```bat
matlab-mcp-server --config C:\Users\MATTIA\source\hermes-dir\matlab-mcp-server\config.yaml
```

…then from an MCP client, in order: `matlab_info` → `matlab_execute(code="disp(6*7);")` (expect `42`) → `matlab_list_files`. All three succeed and the setup is healthy.

---

*Server v0.1.0 · batch mode only. A persistent-session mode (Phase 3) is planned — see `.hermes/plans/2026-10-12_131000-matlab-persistent-session-phase3.md` — but is not part of this build.*
