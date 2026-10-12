# MATLAB Persistent Session (Phase 3-lite) Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task.

**Goal:** Add a persistent, long-lived MATLAB session to the MATLAB MCP server so tool calls share one MATLAB process (variables persist across calls, per-call latency drops from ~10–15 s process startup to milliseconds), without requiring the MATLAB Engine API (blocked: R2024a + Python 3.14).

**Architecture:** A persistent MATLAB process hosts a TCP listener (built-in `tcpip` class, no toolboxes) on 127.0.0.1. The MCP server spawns it as a background subprocess (`matlab -nosplash -nodesktop -batch "listener_main(port)"`), connects over a localhost socket, and exchanges **JSON-lines** (one JSON object per LF-terminated line). A new `PersistentEngineWrapper` mirrors the result-dict shape of the existing batch `MATLABEngineWrapper`, and a `SessionManager` owns the lifecycle (lazy start, auto-restart, status, shutdown). Four new MCP tools manage it; the existing 7 batch tools are untouched.

**Tech Stack:** Python 3.14 (stdlib only: `socket`, `subprocess`, `json`, `threading`, `time`), MATLAB R2024a built-in `tcpip`/`jsonencode`/`jsondecode`/`evalc`, FastMCP 4.x, pytest. No new dependencies.

**Why this design (constraints that shaped it):**
- Engine API for Python is unusable here: latest `matlabengine` requires R2026a; R2024a's build supports only Python 3.9–3.11, venv is 3.14. (Verified against MathWorks compatibility table, 2026-10-12.)
- `matlab -r` does not stream stdout on Windows (established in Phases 1–2), so the ready signal cannot ride on stdout → **fixed port from config** is the handshake channel instead.
- MATLAB `-batch` keeps the process alive for the duration of the command, so an infinite-listener function is a valid persistent host.
- JSON-lines framing: MATLAB output contains arbitrary newlines; JSON encoding makes each message exactly one line, killing an entire class of framing bugs.

**Project root:** `C:\Users\MATTIA\source\hermes-dir\matlab-mcp-server`
**Venv:** `C:\Users\MATTIA\source\hermes-dir\.venv`
**Sandbox:** `C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/matlab-sandbox`
**MATLAB:** `C:/Program Files/MATLAB/R2024a/bin/matlab` (on PATH as `matlab`)

**Protocol spec (normative — implementer, MATLAB and Python sides must match exactly):**

| Direction | Message |
|---|---|
| C→S | `{"cmd": "<matlab code, may span lines>"}` |
| C→S | `{"op": "ping"}` |
| C→S | `{"op": "quit"}` |
| S→C | `{"op": "ready", "version": "...", "platform": "..."}` — **always the first line** |
| S→C | `{"ok": true, "stdout": "..."}` |
| S→C | `{"ok": false, "error": "..."}` |
| S→C | `{"op": "pong"}` |
| S→C | `{"op": "bye"}` — last line, after `quit` |

- UTF-8, each message exactly one line terminated by `\n` (LF).
- Request/response is strictly alternating: one request in flight at a time (enforced by a lock on the Python side).
- A `cmd` that raises is NOT a protocol error: it returns `{"ok": false, "error": "<ME.message>"}`. The session stays alive.
- User code running in the listener lives in the listener **function** workspace → variables persist for the session lifetime, base workspace stays clean.

---

## Task 0: Protocol spike on real MATLAB (gates everything)

**Objective:** De-risk the two unverified assumptions on this machine *before* writing any Python: (a) `matlab -batch` stays alive while a function runs an infinite loop, (b) `tcpip` + JSON-lines works under `-batch` on Windows.

**Files:**
- Create (scratch, not committed): `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\spike\listener_main.m`
- Create (scratch): `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\spike\client.py`

**Step 1: Write the spike listener**

Create `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\spike\listener_main.m`:

```matlab
function listener_main(port)
    t = tcpip('127.0.0.1', port, 'LocalPortMode', 'manual', ...
              'NetworkBufferSize', [65536 65536]);
    t.InputMessageSeparator = char(10);
    t.Timeout = 0;
    listen(t, Inf);
    fwrite(t, [jsonencode(struct('op','ready','version',version,'platform',computer)) char(10)], 'char');
    flush(t);
    while t.Status == 'open'
        try
            line = t.readLine();
        catch
            break;
        end
        if isempty(strtrim(line)), continue; end
        req = jsondecode(line);
        if isfield(req, 'op') && strcmp(req.op, 'ping')
            fwrite(t, [jsonencode(struct('op','pong')) char(10)], 'char');
            flush(t);
        elseif isfield(req, 'op') && strcmp(req.op, 'quit')
            fwrite(t, [jsonencode(struct('op','bye')) char(10)], 'char');
            flush(t);
            break;
        else
            try
                out = evalc(req.cmd);
                fwrite(t, [jsonencode(struct('ok',true,'stdout',out)) char(10)], 'char');
            catch ME
                fwrite(t, [jsonencode(struct('ok',false,'error',ME.message)) char(10)], 'char');
            end
            flush(t);
        end
    end
    close(t);
end
```

**Step 2: Write the spike client**

Create `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\spike\client.py`:

```python
import json, socket, sys

s = socket.create_connection(("127.0.0.1", int(sys.argv[1])), timeout=10)
buf = b""
def read_line():
    global buf
    while b"\n" not in buf:
        buf += s.recv(65536)
    line, buf = buf.split(b"\n", 1)
    return json.loads(line)

print("ready:", read_line())
s.sendall((json.dumps({"op": "ping"}) + "\n").encode())
print("pong:", read_line())
s.sendall((json.dumps({"cmd": "x = 41 + 1; disp(x)"}) + "\n").encode())
print("exec:", read_line())
s.sendall((json.dumps({"op": "quit"}) + "\n").encode())
print("bye:", read_line())
s.close()
```

**Step 3: Run**

```bash
cd "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/spike"
matlab -nosplash -nodesktop -batch "addpath('C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\spike'); listener_main(54999)" &
sleep 20   # MATLAB startup
"C:/Users/MATTIA/source/hermes-dir/.venv/Scripts/python.exe" client.py 54999
wait
```

**Step 4: Verify**

Expected output, exactly:

```
ready: {'op': 'ready', 'version': '24.1.0.2837808', 'platform': 'PCWIN64'}
pong: {'op': 'pong'}
exec: {'ok': True, 'stdout': '42'}
bye: {'op': 'bye'}
```

and the background MATLAB process exits cleanly after `bye` (the `wait` returns, no lingering `matlab.exe` in tasklist).

**Step 5: Record outcome**

Append a "Spike result" note at the bottom of this plan file: PASS/FAIL, timestamp, any deviation (e.g. `version` string format, buffering quirks). If FAIL: stop, diagnose (check `matlab -batch` stdout/exit code; try `-r` variant; try `listen(t, 1)` + accept loop), do not proceed to Task 1.

**Step 6: Commit** (nothing to commit — spike is scratch; note in plan instead)

---

## Task 1: Test doubles + pytest marker

**Objective:** A fake MATLAB executable that speaks the protocol, so all Python-side tests run in <1 s without MATLAB; plus a `integration` marker so real-MATLAB tests are opt-in.

**Files:**
- Create: `matlab-mcp-server/tests/fake_matlab.py`
- Modify: `matlab-mcp-server/pyproject.toml` (append `[tool.pytest.ini_options]`)

**Step 1: Create `tests/fake_matlab.py`**

```python
"""Fake MATLAB for tests: speaks the listener protocol without MATLAB.

Invoked exactly like the wrapper invokes MATLAB:
    python fake_matlab.py -nosplash -nodesktop -batch "<batch code>"
It parses the port out of the -batch argument and serves one client.

Simulated behaviors:
  ready banner with version "FAKE"
  {"op": "ping"}  -> {"op": "pong"}
  {"op": "quit"}  -> {"op": "bye"} then close
  cmd starting with "RAISE" -> {"ok": false, "error": "simulated: <rest>"}
  cmd "SLOW <secs>" -> sleeps, then ok (timeout tests)
  cmd "BIG" -> ok with a 200 KB stdout payload (multi-chunk tests)
  any other cmd -> {"ok": true, "stdout": "FAKE-OUT: <cmd>"}
"""
import json
import re
import socket
import sys
import time


def serve(conn: socket.socket) -> None:
    conn.sendall((json.dumps({"op": "ready", "version": "FAKE",
                              "platform": "FACK64"}) + "\n").encode("utf-8"))
    buf = b""
    while True:
        chunk = conn.recv(65536)
        if not chunk:
            return
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if not line.strip():
                continue
            try:
                req = json.loads(line)
            except json.JSONDecodeError:
                conn.sendall((json.dumps({"ok": False, "error": "bad json"}) + "\n").encode())
                continue
            if req.get("op") == "ping":
                conn.sendall((json.dumps({"op": "pong"}) + "\n").encode())
            elif req.get("op") == "quit":
                conn.sendall((json.dumps({"op": "bye"}) + "\n").encode())
                return
            elif "cmd" in req:
                cmd = req["cmd"]
                if cmd.startswith("RAISE"):
                    conn.sendall((json.dumps({"ok": False,
                                              "error": "simulated: " + cmd[5:].strip()}) + "\n").encode())
                elif cmd.startswith("SLOW"):
                    time.sleep(float(cmd.split()[1]))
                    conn.sendall((json.dumps({"ok": True, "stdout": "done"}) + "\n").encode())
                elif cmd == "BIG":
                    conn.sendall((json.dumps({"ok": True, "stdout": "x" * 200_000}) + "\n").encode())
                else:
                    conn.sendall((json.dumps({"ok": True, "stdout": f"FAKE-OUT: {cmd}"}) + "\n").encode())


def main() -> None:
    batch = sys.argv[sys.argv.index("-batch") + 1]
    port = int(re.search(r"listener_main\((\d+)\)", batch).group(1))
    srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    srv.bind(("127.0.0.1", port))
    srv.listen(1)
    time.sleep(0.2)  # simulate MATLAB startup latency
    conn, _ = srv.accept()
    serve(conn)
    srv.close()


if __name__ == "__main__":
    main()
```

**Step 2: Append to `pyproject.toml`**

```toml
[tool.pytest.ini_options]
markers = ["integration: real-MATLAB tests (deselected by default)"]
addopts = "-m 'not integration'"
```

**Step 3: Verify**

Run: `cd matlab-mcp-server && "C:/Users/MATTIA/source/hermes-dir/.venv/Scripts/python.exe" -m pytest tests/ -q`
Expected: all 18 existing tests still pass (marker deselects nothing yet; no collection errors).

**Step 4: Commit**

```bash
git add tests/fake_matlab.py pyproject.toml
git commit -m "test: fake MATLAB protocol double + integration marker"
```

---

## Task 2: `PersistentEngineWrapper` — start + handshake

**Objective:** Wrapper class skeleton; `start()` materializes the listener `.m` into the sandbox, spawns MATLAB (or the fake) as a background subprocess, connects, and consumes the `ready` banner.

**Files:**
- Create: `matlab-mcp-server/src/engine/persistent_wrapper.py`
- Test: `matlab-mcp-server/tests/test_persistent.py`

**Step 1: Write the failing test** — create `tests/test_persistent.py`:

```python
"""Tests for the persistent MATLAB session (Python side, fake MATLAB)."""
import socket
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.persistent_wrapper import PersistentEngineWrapper

FAKE = [sys.executable, str(Path(__file__).parent / "fake_matlab.py")]
PORT = 54700  # kept distinct per test module to avoid collisions


@pytest.fixture
def wrapper(tmp_path):
    w = PersistentEngineWrapper(
        executable=" ".join(FAKE),  # space-joined: wrapper must split (see note below)
        sandbox_dir=tmp_path,
        port=PORT,
        startup_timeout_s=10,
        request_timeout_s=5,
    )
    yield w
    w.stop(force=True)
```

> **Implementer note (executable form):** the wrapper must accept the executable as a *string* (config-driven, matches `MATLABEngineWrapper`). Implement `start()` with `subprocess.Popen(shlex.split(self.executable) + ["-nosplash", "-nodesktop", "-batch", batch_cmd], ...)` so `"python C:\...\fake_matlab.py"` splits correctly and `"C:/Program Files/MATLAB/R2024a/bin/matlab"` (space in path) stays one token. Import `shlex` in the wrapper.

Add to the same file:

```python
class TestStart:
    def test_start_handshake(self, wrapper):
        wrapper.start()
        assert wrapper.is_alive()
        info = wrapper.info()
        assert info["version"] == "FAKE"
        assert info["platform"] == "FACK64"
        assert info["alive"] is True

    def test_start_timeout_when_no_listener(self, tmp_path):
        w = PersistentEngineWrapper(
            executable=" ".join(FAKE), sandbox_dir=tmp_path,
            port=PORT + 1, startup_timeout_s=2, request_timeout_s=2,
        )
        # Point the fake at a port it will NOT bind by giving a batch arg
        # it cannot parse: simplest — use a non-matching executable.
        w.executable = "python -c \"import time; time.sleep(30)\""
        with pytest.raises(TimeoutError):
            w.start()
        w.stop(force=True)
```

**Step 2: Run to verify failure**

Run: `pytest tests/test_persistent.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.persistent_wrapper'`

**Step 3: Write the implementation** — create `src/engine/persistent_wrapper.py`:

```python
"""Persistent MATLAB session wrapper (Phase 3-lite).

Drives a long-lived MATLAB process hosting a TCP listener
(LISTENER_TEMPLATE below, materialized into the sandbox at start).
Speaks JSON-lines over a localhost socket. Protocol: see plan
.hermes/plans/2026-10-12_131000-matlab-persistent-session-phase3.md.

Result dicts match MATLABEngineWrapper.execute() shape so tool code
can swap engines without changes.
"""

import json
import logging
import shlex
import socket
import subprocess
import threading
import time
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("matlab-mcp-server.persistent")

LISTENER_TEMPLATE = '''\
function listener_main(port)
%LISTENER_MAIN Persistent MATLAB session: JSON-lines protocol over TCP.
%   In:  {"cmd": "<matlab code>"} | {"op": "ping"} | {"op": "quit"}
%   Out: {"op": "ready", ...} (first line)
%        {"ok": true, "stdout": "..."} | {"ok": false, "error": "..."}
%        {"op": "pong"} | {"op": "bye"}
%   Variables set by "cmd" persist in this function's workspace
%   for the lifetime of the session.

    t = tcpip('127.0.0.1', port, 'LocalPortMode', 'manual', ...
              'NetworkBufferSize', [65536 65536]);
    t.InputMessageSeparator = char(10);
    t.Timeout = 0;  % block indefinitely; liveness is client-managed
    listen(t, Inf);

    sendLine(t, struct('op', 'ready', 'version', version, 'platform', computer));

    while t.Status == 'open'
        try
            line = t.readLine();
        catch
            break;  % client disconnected
        end
        if ~ischar(line) || isempty(strtrim(line))
            continue;
        end
        try
            req = jsondecode(line);
        catch ME
            sendLine(t, struct('ok', false, 'error', ['jsondecode: ' ME.message]));
            continue;
        end
        if isstruct(req) && isfield(req, 'op')
            switch req.op
                case 'ping'
                    sendLine(t, struct('op', 'pong'));
                case 'quit'
                    sendLine(t, struct('op', 'bye'));
                    break;
                otherwise
                    sendLine(t, struct('ok', false, 'error', 'unknown op'));
            end
        else
            if ~ischar(getfield_safe(req, 'cmd'))
                sendLine(t, struct('ok', false, 'error', 'missing cmd'));
                continue;
            end
            try
                out = evalc(req.cmd);
                sendLine(t, struct('ok', true, 'stdout', out));
            catch ME
                sendLine(t, struct('ok', false, 'error', ME.message));
            end
        end
    end
    close(t);
end

function sendLine(t, s)
    fwrite(t, [jsonencode(s) char(10)], 'char');
    flush(t);
end

function v = getfield_safe(s, f)
    v = '';
    if isstruct(s) && isfield(s, f)
        v = s.(f);
    end
end
'''


class PersistentEngineWrapper:
    """Owns one persistent MATLAB process + its TCP connection."""

    def __init__(
        self,
        executable: str = "matlab",
        sandbox_dir: Optional[Path] = None,
        port: int = 54321,
        startup_timeout_s: int = 60,
        request_timeout_s: int = 300,
    ):
        self.executable = executable
        self.sandbox_dir = (
            Path(sandbox_dir).resolve() if sandbox_dir is not None else Path.cwd().resolve()
        )
        self.port = port
        self.startup_timeout_s = startup_timeout_s
        self.request_timeout_s = request_timeout_s
        self._proc: Optional[subprocess.Popen] = None
        self._sock: Optional[socket.socket] = None
        self._buf = b""
        self._lock = threading.Lock()
        self._started_at: Optional[float] = None
        self._banner: Optional[dict] = None

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> None:
        """Spawn MATLAB with the listener and complete the handshake."""
        self._write_listener()
        safe_sandbox = str(self.sandbox_dir).replace("\\", "\\\\")
        batch_cmd = f"addpath('{safe_sandbox}'); listener_main({self.port})"
        argv = shlex.split(self.executable) + [
            "-nosplash", "-nodesktop", "-batch", batch_cmd,
        ]
        logger.info(f"Starting persistent MATLAB: {' '.join(argv[:4])} ... port={self.port}")
        self._proc = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        self._connect_with_handshake()
        self._started_at = time.monotonic()

    def _write_listener(self) -> None:
        (self.sandbox_dir / "listener_main.m").write_text(
            LISTENER_TEMPLATE, encoding="utf-8"
        )

    def _connect_with_handshake(self) -> None:
        deadline = time.monotonic() + self.startup_timeout_s
        last_err: Optional[Exception] = None
        while time.monotonic() < deadline:
            if self._proc is not None and self._proc.poll() is not None:
                err = self._proc.stderr.read().decode(errors="replace") if self._proc.stderr else ""
                raise RuntimeError(f"MATLAB exited during startup: {err[-500:]}")
            try:
                s = socket.create_connection(("127.0.0.1", self.port), timeout=3)
                s.settimeout(self.request_timeout_s)
                banner = self._read_line(s)
                if banner.get("op") == "ready":
                    self._sock = s
                    self._banner = banner
                    return
                s.close()
            except (ConnectionRefusedError, TimeoutError, OSError) as e:
                last_err = e
                time.sleep(0.5)
        raise TimeoutError(
            f"MATLAB listener did not become ready on port {self.port} "
            f"within {self.startup_timeout_s}s (last error: {last_err})"
        )

    def stop(self, force: bool = False) -> None:
        """Graceful stop (quit + wait) or force (kill)."""
        if self._sock is not None and not force:
            try:
                with self._lock:
                    self._send_raw({"op": "quit"})
                    self._read_line(self._sock)  # consume bye
            except (OSError, TimeoutError, json.JSONDecodeError):
                pass
        self._close_socket()
        if self._proc is not None:
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                logger.warning("MATLAB did not exit after quit; killing")
                self._proc.kill()
                self._proc.wait(timeout=10)
            self._proc = None
        self._started_at = None
        self._banner = None

    def _close_socket(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            finally:
                self._sock = None
            self._buf = b""

    # -- protocol ----------------------------------------------------------

    def _send_raw(self, obj: dict) -> None:
        if self._sock is None:
            raise ConnectionError("session not connected")
        self._sock.sendall((json.dumps(obj) + "\n").encode("utf-8"))

    def _read_line(self, sock: socket.socket) -> dict:
        while b"\n" not in self._buf:
            chunk = sock.recv(65536)
            if not chunk:
                raise ConnectionError("MATLAB listener closed the connection")
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))

    def _request(self, obj: dict) -> dict:
        with self._lock:
            self._send_raw(obj)
            return self._read_line(self._sock)

    # -- public API (MATLABEngineWrapper-compatible result shape) ----------

    def execute(self, code: str) -> dict[str, Any]:
        try:
            resp = self._request({"cmd": code})
        except (ConnectionError, TimeoutError, OSError) as e:
            return {
                "exit_code": -1, "error": True, "session_dead": True,
                "message": f"session connection failed: {e}",
            }
        if resp.get("ok"):
            return {"exit_code": 0, "stdout": resp.get("stdout", ""), "stderr": ""}
        return {
            "exit_code": 1, "stdout": "", "stderr": "",
            "error": True, "matlab_error": resp.get("error", "unknown error"),
        }

    def ping(self) -> bool:
        try:
            resp = self._request({"op": "ping"})
            return resp.get("op") == "pong"
        except (ConnectionError, TimeoutError, OSError):
            return False

    def is_alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and self._sock is not None
            and self.ping()
        )

    def info(self) -> dict[str, Any]:
        return {
            "version": (self._banner or {}).get("version"),
            "platform": (self._banner or {}).get("platform"),
            "port": self.port,
            "uptime_s": round(time.monotonic() - self._started_at, 1)
            if self._started_at
            else 0,
            "alive": self._sock is not None,
        }
```

**Step 4: Run to verify pass**

Run: `pytest tests/test_persistent.py -v`
Expected: 2 passed.

**Step 5: Commit**

```bash
git add src/engine/persistent_wrapper.py tests/test_persistent.py
git commit -m "feat: PersistentEngineWrapper start/handshake"
```

---

## Task 3: `execute()` + error framing

**Objective:** Round-trip execution and MATLAB-error mapping, verified against the fake's `RAISE`/echo behaviors.

**Files:**
- Test: `matlab-mcp-server/tests/test_persistent.py` (extend)

**Step 1: Write the failing tests**

```python
class TestExecute:
    def test_execute_ok(self, wrapper):
        wrapper.start()
        r = wrapper.execute("x = 1 + 1")
        assert r["exit_code"] == 0
        assert r["stdout"] == "FAKE-OUT: x = 1 + 1"
        assert r["stderr"] == ""

    def test_execute_multiline_code(self, wrapper):
        wrapper.start()
        r = wrapper.execute("a = 1;\nb = 2;\ndisp(a+b)")
        assert r["exit_code"] == 0
        assert "a = 1;" in r["stdout"]

    def test_execute_matlab_error(self, wrapper):
        wrapper.start()
        r = wrapper.execute("RAISE undefined_var")
        assert r["exit_code"] == 1
        assert r["error"] is True
        assert r["matlab_error"] == "simulated: undefined_var"
        # session survives a MATLAB error:
        assert wrapper.ping() is True

    def test_execute_when_dead(self, wrapper):
        wrapper.start()
        wrapper.stop(force=True)
        r = wrapper.execute("x = 1")
        assert r["exit_code"] == -1
        assert r["session_dead"] is True
```

**Step 2: Run** — Expected: FAIL (methods exist from Task 2, so these may already pass — if so, note "covered by Task 2 implementation" and just commit the tests; the TDD value here is locking the contract).

**Step 3: Fix implementation if red; otherwise skip.**

**Step 4: Run** — Expected: all pass.

**Step 5: Commit**

```bash
git add tests/test_persistent.py
git commit -m "test: lock execute() contract (ok, multiline, error, dead)"
```

---

## Task 4: `ping` / `is_alive` / `info`

**Objective:** Liveness semantics, including "alive" vs "process alive but connection dead".

**Files:**
- Test: `matlab-mcp-server/tests/test_persistent.py` (extend)

**Step 1: Write the failing tests**

```python
class TestLiveness:
    def test_ping_true_when_running(self, wrapper):
        wrapper.start()
        assert wrapper.ping() is True
        assert wrapper.is_alive() is True

    def test_ping_false_after_stop(self, wrapper):
        wrapper.start()
        wrapper.stop()
        assert wrapper.ping() is False
        assert wrapper.is_alive() is False

    def test_info_uptime_advances(self, wrapper):
        wrapper.start()
        i1 = wrapper.info()
        time.sleep(0.05)
        i2 = wrapper.info()
        assert i2["uptime_s"] >= i1["uptime_s"]
        assert i1["port"] == PORT
```

(Add `import time` to the test file header.)

**Step 2: Run** — Expected: pass or trivial fix.

**Step 3: Run full module** — `pytest tests/test_persistent.py -v`, all green.

**Step 4: Commit**

```bash
git add tests/test_persistent.py src/engine/persistent_wrapper.py
git commit -m "feat: session liveness (ping/is_alive/info)"
```

---

## Task 5: `stop()` graceful + force

**Objective:** Graceful quit (bye consumed, process exits on its own) and force kill; idempotent double-stop.

**Files:**
- Test: `matlab-mcp-server/tests/test_persistent.py` (extend)

**Step 1: Write the failing tests**

```python
class TestStop:
    def test_stop_graceful_exits_process(self, wrapper):
        wrapper.start()
        proc = wrapper._proc
        wrapper.stop()
        assert proc.poll() is not None  # exited, not killed
        assert wrapper._sock is None

    def test_stop_idempotent(self, wrapper):
        wrapper.start()
        wrapper.stop()
        wrapper.stop()  # must not raise
        assert wrapper._proc is None

    def test_stop_force_without_connection(self, wrapper):
        wrapper.start()
        wrapper._sock.close()
        wrapper._sock = None
        wrapper.stop(force=True)  # must not raise
        assert wrapper._proc is None
```

**Step 2: Run** — Expected: pass or trivial fix.

**Step 3: Run full module** — all green.

**Step 4: Commit**

```bash
git add tests/test_persistent.py src/engine/persistent_wrapper.py
git commit -m "feat: graceful/force stop, idempotent"
```

---

## Task 6: Multi-chunk reassembly + concurrent-request lock

**Objective:** Large responses (>64 KB, split across TCP segments) reassemble correctly; concurrent tool calls cannot interleave on the socket.

**Files:**
- Test: `matlab-mcp-server/tests/test_persistent.py` (extend)

**Step 1: Write the failing tests**

```python
class TestRobustness:
    def test_large_response_reassembles(self, wrapper):
        wrapper.start()
        r = wrapper.execute("BIG")
        assert r["exit_code"] == 0
        assert len(r["stdout"]) == 200_000

    def test_concurrent_requests_do_not_interleave(self, wrapper):
        import concurrent.futures

        wrapper.start()
        with concurrent.futures.ThreadPoolExecutor(max_workers=4) as ex:
            futs = [ex.submit(wrapper.execute, f"task-{i}") for i in range(8)]
            results = [f.result() for f in futs]
        assert all(r["exit_code"] == 0 for r in results)
        outs = sorted(r["stdout"] for r in results)
        assert outs == sorted(f"FAKE-OUT: task-{i}" for i in range(8))
```

**Step 2: Run** — Expected: `test_large_response_reassembles` passes (buffering already in `_read_line`); `test_concurrent_requests_do_not_interleave` passes only if `_request` holds the lock (it does from Task 2). If red, fix `_request`.

**Step 3: Run full module** — all green.

**Step 4: Commit**

```bash
git add tests/test_persistent.py src/engine/persistent_wrapper.py
git commit -m "test: large-payload reassembly + concurrent request lock"
```

---

## Task 7: `SessionManager` (lifecycle, auto-restart, status)

**Objective:** Own start/restart/stop policy and expose `execute()` with automatic crash recovery, so tool code never touches the wrapper's failure modes.

**Files:**
- Create: `matlab-mcp-server/src/engine/session.py`
- Test: `matlab-mcp-server/tests/test_session.py`

**Step 1: Write the failing tests** — create `tests/test_session.py`:

```python
"""Tests for SessionManager (fake MATLAB)."""
import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.persistent_wrapper import PersistentEngineWrapper
from engine.session import SessionManager

FAKE = f"{sys.executable} {Path(__file__).parent / 'fake_matlab.py'}"
PORT = 54710


def make_manager(tmp_path, **kw):
    w = PersistentEngineWrapper(executable=FAKE, sandbox_dir=tmp_path,
                                port=PORT, startup_timeout_s=10,
                                request_timeout_s=5)
    return SessionManager(w, **kw)


class TestSessionManager:
    def test_lazy_start_on_first_execute(self, tmp_path):
        m = make_manager(tmp_path)
        assert m.status()["state"] == "stopped"
        r = m.execute("hello")
        assert r["exit_code"] == 0
        assert m.status()["state"] == "running"
        m.shutdown()

    def test_status_reports_version(self, tmp_path):
        m = make_manager(tmp_path)
        m.execute("x")
        s = m.status()
        assert s["info"]["version"] == "FAKE"
        m.shutdown()

    def test_auto_restart_after_crash(self, tmp_path):
        m = make_manager(tmp_path, auto_restart=True, max_restarts=3)
        m.execute("warm")
        # simulate MATLAB crash: kill the process out from under it
        m.wrapper._proc.kill()
        m.wrapper._proc.wait()
        r = m.execute("after-crash")
        assert r["exit_code"] == 0
        assert m.status()["restarts"] == 1
        m.shutdown()

    def test_max_restarts_exhausted(self, tmp_path):
        m = make_manager(tmp_path, auto_restart=True, max_restarts=1)
        m.execute("warm")
        m.wrapper._proc.kill()
        m.wrapper._proc.wait()
        # force every start to fail by occupying the port
        import socket
        blocker = socket.socket()
        blocker.bind(("127.0.0.1", PORT))
        blocker.listen(1)
        try:
            r = m.execute("doomed")
            assert r["exit_code"] == -1
            assert r["error"] is True
        finally:
            blocker.close()
        m.shutdown()
```

**Step 2: Run to verify failure**

Run: `pytest tests/test_session.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'engine.session'`

**Step 3: Write the implementation** — create `src/engine/session.py`:

```python
"""Lifecycle manager for the persistent MATLAB session."""

import logging
from typing import Any

logger = logging.getLogger("matlab-mcp-server.session")


class SessionManager:
    """Policies: lazy start, auto-restart with a cap, explicit shutdown.

    The wrapper is created by the caller (server.py) and injected, keeping
    this class free of construction config.
    """

    def __init__(self, wrapper, auto_restart: bool = True, max_restarts: int = 3):
        self.wrapper = wrapper
        self.auto_restart = auto_restart
        self.max_restarts = max_restarts
        self._restarts = 0
        self._state = "stopped"  # stopped | starting | running | dead

    def ensure_started(self):
        if self.wrapper.is_alive():
            self._state = "running"
            return self.wrapper
        self._do_start()
        return self.wrapper

    def _do_start(self) -> None:
        self._state = "starting"
        try:
            self.wrapper.stop(force=True)  # clear zombies from a dead session
        except Exception:  # noqa: BLE001 - cleanup must never mask the real error
            pass
        self.wrapper.start()
        self._state = "running"
        if self._restarts:
            logger.info(f"session (re)started (restart #{self._restarts})")

    def execute(self, code: str) -> dict[str, Any]:
        try:
            self.ensure_started()
            result = self.wrapper.execute(code)
        except (TimeoutError, RuntimeError) as e:
            self._state = "dead"
            return {"exit_code": -1, "error": True, "message": str(e)}

        if result.get("session_dead") and self.auto_restart:
            if self._restarts < self.max_restarts:
                self._restarts += 1
                logger.warning("session died mid-request; restarting and retrying once")
                try:
                    self.ensure_started()
                    result = self.wrapper.execute(code)
                except (TimeoutError, RuntimeError) as e:
                    return {"exit_code": -1, "error": True, "message": str(e)}
            else:
                result["message"] = (
                    result.get("message", "")
                    + " (auto-restart exhausted; call matlab_session_start after fixing the cause)"
                )
        elif result.get("session_dead"):
            self._state = "dead"
        return result

    def status(self) -> dict[str, Any]:
        alive = self.wrapper.is_alive()
        if alive:
            self._state = "running"
        return {
            "state": "running" if alive else self._state,
            "restarts": self._restarts,
            "info": self.wrapper.info(),
        }

    def shutdown(self) -> None:
        try:
            self.wrapper.stop()
        finally:
            self._state = "stopped"
```

**Step 4: Run to verify pass**

Run: `pytest tests/test_session.py -v`
Expected: 4 passed.

**Step 5: Commit**

```bash
git add src/engine/session.py tests/test_session.py
git commit -m "feat: SessionManager with auto-restart and status"
```

---

## Task 8: Session MCP tools

**Objective:** Four tools: `matlab_session_start`, `matlab_session_execute`, `matlab_session_status`, `matlab_session_stop`.

**Files:**
- Create: `matlab-mcp-server/src/tools/session.py`
- Test: `matlab-mcp-server/tests/test_session_tools.py`

**Step 1: Write the failing test** — create `tests/test_session_tools.py`:

```python
"""Tool-registration test for session tools (no MATLAB needed)."""
import asyncio
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from fastmcp import FastMCP

from engine.persistent_wrapper import PersistentEngineWrapper
from engine.session import SessionManager
from tools import session as session_tools

FAKE = f"{sys.executable} {Path(__file__).parent / 'fake_matlab.py'}"


def test_session_tools_register(tmp_path):
    w = PersistentEngineWrapper(executable=FAKE, sandbox_dir=tmp_path,
                                port=54720, startup_timeout_s=10,
                                request_timeout_s=5)
    m = SessionManager(w)
    server = FastMCP("test-session-tools")
    session_tools.register(server, m)
    names = [t.name for t in asyncio.run(server._list_tools())]
    for expected in (
        "matlab_session_start",
        "matlab_session_execute",
        "matlab_session_status",
        "matlab_session_stop",
    ):
        assert expected in names
```

**Step 2: Run to verify failure** — Expected: `ModuleNotFoundError: No module named 'tools.session'`

**Step 3: Write the implementation** — create `src/tools/session.py`:

```python
"""Tool definitions for the persistent MATLAB session (Phase 3-lite)."""

import json

from fastmcp import FastMCP


def register(server: FastMCP, sessions) -> None:
    """Register session tools. `sessions` is a SessionManager."""

    @server.tool()
    def matlab_session_start() -> str:
        """Start (or reuse) the persistent MATLAB session.

        Idempotent: if the session is already running, returns its status
        without restarting. First start takes ~10-20 s (MATLAB launch).

        Returns:
            JSON with state, restarts, MATLAB version/platform, port, uptime.
        """
        sessions.ensure_started()
        return json.dumps(sessions.status(), indent=2, default=str)

    @server.tool()
    def matlab_session_execute(code: str, timeout_s: int = 300) -> str:
        """Execute MATLAB code in the persistent session workspace.

        Variables persist across calls until the session is stopped, and
        per-call latency is milliseconds (no process startup). The session
        is started automatically if not running. Prefer this over
        matlab_execute for iterative work; use matlab_execute for
        self-contained one-shots.

        Args:
            code: MATLAB code to execute (may span lines)
            timeout_s: Maximum execution time in seconds (default: 300)

        Returns:
            JSON with exit_code, stdout, and optional error details.
        """
        sessions.wrapper.request_timeout_s = timeout_s
        result = sessions.execute(code)
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    def matlab_session_status() -> str:
        """Report persistent session state: running/stopped/dead, uptime,
        restart count, MATLAB version and platform.

        Returns:
            JSON status object.
        """
        return json.dumps(sessions.status(), indent=2, default=str)

    @server.tool()
    def matlab_session_stop() -> str:
        """Stop the persistent MATLAB session. The MATLAB process exits
        and all in-workspace variables are lost (save them to the sandbox
        first if needed).

        Returns:
            JSON status object (state: stopped).
        """
        sessions.shutdown()
        return json.dumps(sessions.status(), indent=2, default=str)
```

**Step 4: Run to verify pass** — Expected: 1 passed.

**Step 5: Commit**

```bash
git add src/tools/session.py tests/test_session_tools.py
git commit -m "feat: session MCP tools (start/execute/status/stop)"
```

---

## Task 9: Real-MATLAB integration test

**Objective:** Prove the full loop on R2024a, including the property the whole feature exists for: **variable persistence across calls**.

**Files:**
- Create: `matlab-mcp-server/tests/test_integration_session.py`

**Step 1: Write the test**

```python
"""Real-MATLAB integration tests. Deselected by default; run with:
    pytest -m integration -v
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.persistent_wrapper import PersistentEngineWrapper
from engine.session import SessionManager

MATLAB = "C:/Program Files/MATLAB/R2024a/bin/matlab"
SANDBOX = Path("C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/matlab-sandbox")
PORT = 54730


@pytest.fixture(scope="module")
def manager():
    w = PersistentEngineWrapper(
        executable=MATLAB, sandbox_dir=SANDBOX, port=PORT,
        startup_timeout_s=90, request_timeout_s=60,
    )
    m = SessionManager(w, auto_restart=True, max_restarts=1)
    yield m
    m.shutdown()


@pytest.mark.integration
class TestRealSession:
    def test_start_and_info(self, manager):
        manager.ensure_started()
        s = manager.status()
        assert s["state"] == "running"
        assert s["info"]["version"].startswith("24.1.0")
        assert s["info"]["platform"] == "PCWIN64"

    def test_variable_persistence(self, manager):
        r1 = manager.execute("tftb_phase3_var = 42;")
        assert r1["exit_code"] == 0
        assert r1["stdout"] == ""  # no output (semicolon)
        r2 = manager.execute("disp(tftb_phase3_var);")
        assert r2["exit_code"] == 0
        assert r2["stdout"].strip() == "42"

    def test_matlab_error_keeps_session(self, manager):
        r = manager.execute("disp(undefined_variable_xyz);")
        assert r["exit_code"] == 1
        assert r["error"] is True
        assert manager.status()["state"] == "running"

    def test_stop(self, manager):
        manager.shutdown()
        s = manager.status()
        assert s["state"] == "stopped"
        assert s["info"]["alive"] is False
```

**Step 2: Run**

Run: `pytest -m integration -v` (takes ~30–60 s: one MATLAB start/stop)
Expected: 4 passed.

**Step 3: If `test_start_and_info` hangs at startup**

Diagnose in order: (1) `netstat -ano | findstr 54730` — is the port bound? (2) re-run the Task 0 spike — regression? (3) check the wrapper's logged startup error (it raises with the last 500 chars of MATLAB stderr). Fix root cause, re-run.

**Step 4: Commit**

```bash
git add tests/test_integration_session.py
git commit -m "test: real-MATLAB session integration (persistence, errors, stop)"
```

---

## Task 10: Config + server wiring

**Objective:** `session` config section (with defaults so an absent section still works), lazy wiring in `server.py`, session included in `DEFAULT_CONFIG`.

**Files:**
- Modify: `matlab-mcp-server/config.yaml`
- Modify: `matlab-mcp-server/src/server.py`
- Test: manual (server startup)

**Step 1: Append to `config.yaml`**

```yaml
# Persistent session (Phase 3-lite): long-lived MATLAB over localhost TCP
session:
  enabled: true
  port: 54321               # 127.0.0.1 only; change if colliding
  auto_restart: true
  max_restarts: 3           # per server lifetime
  startup_timeout_s: 90     # MATLAB launch can take ~20 s; be generous
  request_timeout_s: 300
```

**Step 2: Wire `server.py`**

In `main()`, after `matlab_engine` is constructed (currently around line 71), add:

```python
    # Persistent session (Phase 3-lite) — lazy: started on first session call
    session_cfg = config.get("session", {})
    sessions = None
    if session_cfg.get("enabled", True):
        from engine.persistent_wrapper import PersistentEngineWrapper
        from engine.session import SessionManager

        pw = PersistentEngineWrapper(
            executable=matlab_executable,
            sandbox_dir=sandbox_dir,
            port=session_cfg.get("port", 54321),
            startup_timeout_s=session_cfg.get("startup_timeout_s", 90),
            request_timeout_s=session_cfg.get("request_timeout_s", 300),
        )
        sessions = SessionManager(
            pw,
            auto_restart=session_cfg.get("auto_restart", True),
            max_restarts=session_cfg.get("max_restarts", 3),
        )
        logger.info("Persistent session enabled (lazy start, port %s)",
                    session_cfg.get("port", 54321))
```

In the tool-registration block (currently `from tools import execute, files, info`), change to:

```python
    from tools import execute, files, info
    from tools import session as session_tools

    execute.register(server, matlab_engine)
    files.register(server, sandbox)
    info.register(server, matlab_engine)
    if sessions is not None:
        session_tools.register(server, sessions)
```

In `DEFAULT_CONFIG`, add:

```python
    "session": {
        "enabled": True,
        "port": 54321,
        "auto_restart": True,
        "max_restarts": 3,
        "startup_timeout_s": 90,
        "request_timeout_s": 300,
    },
```

**Step 3: Verify — dev server startup + tool listing**

```bash
cd "C:/Users/MATTIA/source/hermes-dir"
timeout 15 ".venv/Scripts/python.exe" "matlab-mcp-server/src/server.py" 2>&1 | head -25
```

Expected: `Sandbox directory ensured ...`, `Loaded config from ...config.yaml`, `Persistent session enabled (lazy start, port 54321)`, FastMCP banner, no traceback. (Session is NOT started here — lazy.)

**Step 4: Verify — full suite still green**

Run: `pytest matlab-mcp-server/tests/ -q`
Expected: all unit tests pass (integration deselected).

**Step 5: Commit**

```bash
git add config.yaml src/server.py
git commit -m "feat: session config + server wiring (lazy start)"
```

---

## Task 11: Rebuild wheel + end-to-end MCP handshake with session

**Objective:** Ship the new code in the wheel and prove the installed layout serves all 11 tools, including a live session round-trip over MCP stdio.

**Files:**
- Modify: `C:\Users\MATTIA\AppData\Local\hermes\cache\scratch\wheel_handshake_test.py` (extend)
- Output: `matlab-mcp-server/dist/matlab_mcp_server-0.1.0-py3-none-any.whl` (rebuilt)

**Step 1: Bump nothing, rebuild**

```bash
cd "C:/Users/MATTIA/source/hermes-dir"
rm -f matlab-mcp-server/dist/*.whl
".venv/Scripts/pip.exe" wheel "./matlab-mcp-server" -w "matlab-mcp-server/dist" --no-deps --no-build-isolation
```

Expected: `Successfully built matlab-mcp-server`.

**Step 2: Verify wheel contents**

```bash
".venv/Scripts/python.exe" -c "
import zipfile
z = zipfile.ZipFile('matlab-mcp-server/dist/matlab_mcp_server-0.1.0-py3-none-any.whl')
names = z.namelist()
for n in ('server.py', 'engine/persistent_wrapper.py', 'engine/session.py', 'tools/session.py'):
    assert n in names, n
print('wheel contents OK:', len(names), 'entries')
"
```

**Step 3: Extend the handshake test** — in `wheel_handshake_test.py`, after the existing `matlab_info` call, add:

```python
# 5. session round-trip (real MATLAB, ~20 s)
send({"jsonrpc": "2.0", "id": 4, "method": "tools/call",
      "params": {"name": "matlab_session_start", "arguments": {}}})
s = recv()
assert s["id"] == 4, s
print("SESSION_START OK:", s["result"]["content"][0]["text"][:120].replace("\n", " "))

send({"jsonrpc": "2.0", "id": 5, "method": "tools/call",
      "params": {"name": "matlab_session_execute",
                 "arguments": {"code": "e2e_var = 7;"}}})
r5 = recv()
assert r5["id"] == 5 and '"exit_code": 0' in r5["result"]["content"][0]["text"], r5

send({"jsonrpc": "2.0", "id": 6, "method": "tools/call",
      "params": {"name": "matlab_session_execute",
                 "arguments": {"code": "disp(e2e_var);"}}})
r6 = recv()
assert "7" in r6["result"]["content"][0]["text"], r6
print("SESSION PERSISTENCE OK")

send({"jsonrpc": "2.0", "id": 7, "method": "tools/call",
      "params": {"name": "matlab_session_stop", "arguments": {}}})
r7 = recv()
assert "stopped" in r7["result"]["content"][0]["text"], r7
print("SESSION_STOP OK")
```

**Step 4: Run**

```bash
cd "C:/Users/MATTIA/source/hermes-dir"
rm -rf "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/wheel-unpack"
mkdir -p "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/wheel-unpack"
".venv/Scripts/python.exe" -m zipfile -e "matlab-mcp-server/dist/matlab_mcp_server-0.1.0-py3-none-any.whl" "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/wheel-unpack"
".venv/Scripts/python.exe" "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/wheel_handshake_test.py" "C:/Users/MATTIA/AppData/Local/hermes/cache/scratch/wheel-unpack" "C:/Users/MATTIA/source/hermes-dir/.venv/Scripts/python.exe"
```

Expected: all previous checks plus `SESSION_START OK`, `SESSION PERSISTENCE OK`, `SESSION_STOP OK`, `ALL CHECKS PASSED`. (Note: this run uses DEFAULT_CONFIG — `matlab` from PATH, temp-dir sandbox — so it also re-verifies the installed-layout fallback with the session.)

**Step 5: Reinstall into the venv**

```bash
".venv/Scripts/pip.exe" install --force-reinstall --no-deps "matlab-mcp-server/dist/matlab_mcp_server-0.1.0-py3-none-any.whl"
```

**Step 6: Commit**

```bash
git add dist/ 2>/dev/null || true
git commit -m "release: wheel v0.1.0 with persistent session" --allow-empty
```

(dist/ is typically gitignored; the commit records the release step. If dist/ is tracked, add the new .whl.)

---

## Task 12: Documentation

**Objective:** README section covering session usage, config, and operational notes.

**Files:**
- Modify: `matlab-mcp-server/README.md`

**Step 1: Add a "Persistent Session (Phase 3-lite)" section** after "Available Tools", documenting:

- What it is: one long-lived MATLAB process, variables persist, ms-level calls; how it differs from `matlab_execute` (stateless, ~10–15 s per call).
- The 4 session tools with examples:
  ```
  matlab_session_start()
  matlab_session_execute(code="load('data.mat'); process;")
  matlab_session_execute(code="save('out.mat','result');")   # persist to disk
  matlab_session_status()
  matlab_session_stop()
  ```
- Config keys (`session.*`) and defaults.
- Operational notes:
  - Lazy start: first `matlab_session_execute`/`matlab_session_start` pays the ~10–20 s MATLAB launch; subsequent calls are fast.
  - Auto-restart: up to `max_restarts` per server lifetime after a crash; user code calling `exit`/`quit` also kills the session and triggers restart.
  - Save before stopping: workspace variables die with the process; `save(...)` to the sandbox first.
  - One session at a time; one request in flight at a time (long jobs block the session).
  - Cleanup: if the MCP server is killed hard, an orphaned MATLAB may linger — find it via `netstat -ano | findstr 54321` and `taskkill /PID <pid> /F`.
  - Memory: long sessions accumulate workspace memory; `clear` via `matlab_session_execute` or stop/start.
- Security: listener binds 127.0.0.1 only, no authentication — single-user machine assumption.

**Step 2: Verify** — read the rendered section; check every config key and tool name matches the code.

**Step 3: Commit**

```bash
git add README.md
git commit -m "docs: persistent session usage and operations"
```

---

## Files changed (summary)

| File | Action | Tasks |
|---|---|---|
| `src/engine/persistent_wrapper.py` | Create | 2–6 |
| `src/engine/session.py` | Create | 7 |
| `src/tools/session.py` | Create | 8 |
| `tests/fake_matlab.py` | Create | 1 |
| `tests/test_persistent.py` | Create | 2–6 |
| `tests/test_session.py` | Create | 7 |
| `tests/test_session_tools.py` | Create | 8 |
| `tests/test_integration_session.py` | Create | 9 |
| `pyproject.toml` | Modify (pytest marker) | 1 |
| `config.yaml` | Modify (session section) | 10 |
| `src/server.py` | Modify (wiring, DEFAULT_CONFIG) | 10 |
| `README.md` | Modify (docs) | 12 |
| `dist/*.whl` | Rebuild | 11 |

Untouched on purpose: `src/engine/engine_wrapper.py`, `src/engine/sandbox.py`, `src/tools/{execute,files,info}.py`, all existing tests.

## Tests / validation (full matrix)

| Suite | Command | MATLAB needed | Expected |
|---|---|---|---|
| Unit (fake) | `pytest tests/ -q` | No | all pass, <10 s |
| Integration | `pytest -m integration -v` | Yes (~40 s) | 4 passed |
| Dev server | `timeout 15 python src/server.py` | No (lazy) | clean startup, 11 tools |
| Wheel e2e | `wheel_handshake_test.py` (extended) | Yes (~60 s) | ALL CHECKS PASSED |
| Live connector | Hermes MCP reconnect | Yes | 11 tools registered |

## Risks, tradeoffs, open questions

**Risks (ordered by likelihood of biting):**
1. **`-batch` + infinite loop on Windows** — the single unverified assumption; Task 0 gates all other work. Fallback if it fails: host the listener via `matlab -r "listener_main(port)"` (no stdout needed for handshake, so the Windows `-r` stdout quirk is irrelevant) — same protocol, different spawn flags.
2. **Zombie MATLAB after hard MCP-server kill** — mitigated by design (listener exits on client disconnect: `readLine` error → `break` → function returns → `-batch` ends), but a kill -9 between connect and first read can orphan. Documented manual cleanup; optional PID file is out of scope (YAGNI).
3. **Port collision** — fixed port from config; on collision the MATLAB listener fails to bind, exits, and Python raises a clear `TimeoutError` at start. No port auto-negotiation (would need a discovery channel; the fixed port keeps the design simple).
4. **Long jobs block the session** — one request in flight at a time by design (socket is single-reader). Acceptable for agent use; a submit/poll job pattern is a future extension, not this plan.
5. **Memory growth in long sessions** — inherent to persistence; `clear`/restart is the mitigation. No cap mechanism (YAGNI).
6. **`jsonencode` of huge structs** — we only encode scalars/strings, never workspaces; `whos`-style dumps are bounded by the user's `disp`.

**Tradeoffs accepted:**
- No Engine API object marshalling (`eng.workspace.get`-style direct variable access). Variables cross the boundary via `disp`/`save` to .mat — same as batch mode, so no capability regression.
- Single session, single client (the MCP server). No multi-client/multi-session (YAGNI).
- No authentication on the listener: localhost-only binding, single-user machine.

**Open questions (decide before Task 10 if you care):**
1. Lazy start (chosen) vs auto-start at MCP server startup — auto-start costs ~20 s of server boot for users who never touch a session.
2. Should `matlab_execute` (batch) silently route through the session when one is running? Chosen: **no** — explicit tools, predictable cost.
3. Session port 54321 — fine, or prefer a different default to dodge collisions with other local services?

## Spike result

_(fill in after Task 0: PASS/FAIL, timestamp, deviations)_
