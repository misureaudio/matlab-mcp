"""End-to-end MCP handshake test against the wheel's extracted contents.

Simulates the installed layout: wheel unpacked into a dir on sys.path,
no project-root config.yaml present (exercises DEFAULT_CONFIG fallback).
"""
import json
import os
import subprocess
import sys
import time

UNPACK_DIR = sys.argv[1]
PY = sys.argv[2]  # venv python

env = dict(os.environ)
env["PYTHONPATH"] = UNPACK_DIR

proc = subprocess.Popen(
    [PY, "-c", "from server import main; main()"],
    stdin=subprocess.PIPE,
    stdout=subprocess.PIPE,
    stderr=subprocess.PIPE,
    text=True,
    env=env,
)

def send(obj):
    proc.stdin.write(json.dumps(obj) + "\n")
    proc.stdin.flush()

def recv(timeout=60):
    # read one line (MCP stdio = newline-delimited JSON-RPC)
    line = proc.stdout.readline()
    if not line:
        err = proc.stderr.read()
        raise RuntimeError(f"Server closed stdout. stderr:\n{err}")
    return json.loads(line)

# 1. initialize
send({
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2024-11-05",
        "capabilities": {},
        "clientInfo": {"name": "wheel-test", "version": "0.1"},
    },
})
init = recv()
assert init.get("id") == 1, f"bad init response: {init}"
print("INIT OK:", init["result"]["serverInfo"]["name"],
      "| protocol", init["result"]["protocolVersion"])

# 2. initialized notification
send({"jsonrpc": "2.0", "method": "notifications/initialized"})

# 3. tools/list
send({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
tools = recv()
assert tools.get("id") == 2, f"bad tools response: {tools}"
names = sorted(t["name"] for t in tools["result"]["tools"])
print(f"TOOLS OK: {len(names)} tools")
for n in names:
    print("  -", n)

expected = {
    "matlab_execute", "matlab_run_script", "matlab_upload_file",
    "matlab_download_file", "matlab_list_files", "matlab_info",
    "matlab_diagnose",
}
missing = expected - set(names)
assert not missing, f"missing tools: {missing}"

# 4. call matlab_info (real MATLAB round-trip)
send({"jsonrpc": "2.0", "id": 3, "method": "tools/call",
      "params": {"name": "matlab_info", "arguments": {}}})
info = recv()
assert info.get("id") == 3, f"bad info response: {info}"
text = info["result"]["content"][0]["text"]
print("MATLAB_INFO OK:", text.replace("\n", " | "))

proc.stdin.close()
try:
    proc.wait(timeout=10)
except subprocess.TimeoutExpired:
    proc.kill()

print("\nALL CHECKS PASSED")
