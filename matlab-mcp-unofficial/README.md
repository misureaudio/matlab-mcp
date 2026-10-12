# MATLAB MCP Server

An MCP (Model Context Protocol) server that provides an interface between AI agents and MATLAB batch mode execution.

## Features

- Execute MATLAB code in batch mode
- Run .m script files with optional variable output
- Upload/download files to/from MATLAB sandbox directory
- Query MATLAB version and system information
- Run diagnostic checks on MATLAB environment

## Architecture

```
┌─────────────┐     MCP Protocol      ┌──────────────────┐    subprocess     ┌─────────────┐
│   Agent /   │ ◄──────────────────►  │  MATLAB MCP      │ ◄────────────────►  │   MATLAB    │
│  Client     │                       │  Server          │                     │  (batch)    │
└─────────────┘                       └──────────────────┘                     └─────────────┘
                                              │
                                              ▼
                                       ┌──────────────────┐
                                       │   File System    │
                                       │   (sandbox dir)  │
                                       └──────────────────┘
```

## Installation

### Prerequisites

- Python 3.10+
- MATLAB R2020a or later (with valid license)
- MATLAB must be accessible from the command line

### Setup

```bash
# Navigate to project directory
cd matlab-mcp-server

# Create virtual environment (if not already created)
python -m venv .venv

# Activate virtual environment
# On Windows:
.venv\Scripts\activate
# On macOS/Linux:
source .venv/bin/activate

# Install dependencies
pip install -e .
```

## Configuration

Edit `config.yaml` to configure:

```yaml
matlab:
  executable: C:/Program Files/MATLAB/R2024a/bin/matlab  # Full path to MATLAB binary
  sandbox_dir: C:/Users/username/AppData/Local/Temp/matlab-sandbox  # Sandbox directory
  default_timeout_s: 300    # Max execution time per command (seconds)

paths:
  sandbox_dir: C:/Users/username/AppData/Local/Temp/matlab-sandbox  # Must match above

security:
  max_upload_size_mb: 100
  allowed_extensions: [".m", ".mat", ".json", ".csv", ".txt", ".png", ".jpg"]

logging:
  level: INFO
  format: json
```

### Important Notes

1. **MATLAB Path**: Use the full absolute path to the MATLAB executable. On Windows, this is typically:
   - `C:/Program Files/MATLAB/R2024a/bin/matlab` (adjust version as needed)

2. **Sandbox Directory**: This is where all file operations occur. The directory must exist before starting the server. Create it with:
   ```bash
   mkdir -p "C:/Users/username/AppData/Local/Temp/matlab-sandbox"
   ```

3. **Path Format**: Use forward slashes in paths, even on Windows.

## Usage

### Starting the Server

```bash
# From the project directory
python src/server.py

# Or with custom config
python src/server.py --config /path/to/config.yaml
```

The server uses stdio transport by default. For SSE transport (for remote access), modify the `server.run()` call in `server.py`.

### MCP Client Configuration

Add to your MCP client configuration (e.g., `mcp.json` for Claude Desktop):

```json
{
  "mcpServers": {
    "matlab": {
      "command": "C:/Users/username/AppData/Local/hermes/.venv/Scripts/python.exe",
      "args": [
        "C:/Users/username/source/hermes-dir/matlab-mcp-server/src/server.py"
      ]
    }
  }
}
```

## Available Tools

### 1. `matlab_execute`

Execute MATLAB code in batch mode.

**Parameters:**
- `code` (string, required): MATLAB code to execute. **Use single quotes for strings.**
- `timeout_s` (integer, optional): Maximum execution time in seconds (default: 300)

**Example:**
```python
result = matlab_execute(code="x = 1:5; disp(x);")
# Output: { "exit_code": 0, "stdout": "1     2     3     4     5", ... }
```

**Important:** Use single quotes for MATLAB strings, not double quotes:
```matlab
% CORRECT
save('mydata.mat', 'myvar');
disp('Hello');

% INCORRECT (will fail)
save("mydata.mat", "myvar");
disp("Hello");
```

### 2. `matlab_run_script`

Execute a MATLAB .m script file with optional variable output.

**Parameters:**
- `script_path` (string, required): Path to the .m file (relative to sandbox)
- `output_vars` (list of strings, optional): Variable names to save as .mat files

**Example:**
```python
# First upload a script
upload_file(content_base64="...", filename="myscript.m")

# Then run it
result = matlab_run_script(script_path="myscript.m", output_vars=["result", "status"])
# .mat files will be saved in the sandbox directory
```

### 3. `matlab_upload_file`

Upload a file to the MATLAB sandbox directory.

**Parameters:**
- `content_base64` (string, required): Base64-encoded content of the file
- `filename` (string, required): Target filename in sandbox

**Example:**
```python
import base64

with open("local_file.csv", "rb") as f:
    content = base64.b64encode(f.read()).decode()

matlab_upload_file(content_base64=content, filename="data.csv")
```

### 4. `matlab_download_file`

Download a file from the MATLAB sandbox directory.

**Parameters:**
- `filename` (string, required): Filename in sandbox to download

**Returns:** Base64-encoded content along with metadata

**Example:**
```python
result = matlab_download_file(filename="output.mat")
# Parse base64_content from result and decode to file
```

### 5. `matlab_list_files`

List files available in the MATLAB sandbox directory.

**Parameters:**
- `pattern` (string, optional): Glob pattern to filter files (default: '*')

**Example:**
```python
result = matlab_list_files(pattern="*.mat")
# Output: "test1.mat (175KB)\ntest2.mat (181KB)"
```

### 6. `matlab_info`

Return MATLAB version, platform, and installation information.

**Parameters:** None

**Example:**
```python
result = matlab_info()
# Output: { "version": "24.1.0.2837808 (R2024a) Update 7", "platform": "PCWIN64", ... }
```

### 7. `matlab_diagnose`

Run diagnostic checks on MATLAB environment.

**Parameters:**
- `toolboxes` (list of strings, optional): Specific toolboxes to check

**Example:**
```python
result = matlab_diagnose(toolboxes=["Signal Processing", "Statistics"])
# Output: Shows which toolboxes are available
```

## Troubleshooting

### "Unable to resolve the name" errors

This typically means:
1. The sandbox directory doesn't exist - create it
2. You're using double quotes instead of single quotes in MATLAB code
3. The file path is incorrect

### MATLAB not found

Ensure the `executable` path in `config.yaml` points to the correct MATLAB binary:
```bash
# Find MATLAB location on Windows
where matlab
# Or check:
"C:\Program Files\MATLAB\R2024a\bin\matlab.exe" -batch "disp(version); exit(0)"
```

### Timeout errors

Increase `default_timeout_s` in `config.yaml` for long-running computations.

### Permission errors

Ensure the sandbox directory is writable by the user running the MCP server.

## Project Structure

```
matlab-mcp-server/
├── config.yaml           # Configuration file
├── pyproject.toml        # Python project configuration
├── README.md             # This file
├── scripts/
│   └── wrapper.m         # Example wrapper script
├── src/
│   ├── server.py         # MCP server entry point
│   ├── engine/
│   │   ├── __init__.py
│   │   ├── engine_wrapper.py  # MATLAB subprocess wrapper
│   │   └── sandbox.py         # Sandbox directory management
│   └── tools/
│       ├── __init__.py
│       ├── execute.py     # Execution tools
│       ├── files.py       # File management tools
│       └── info.py        # Information tools
└── tests/
    └── test_execute.py   # Test suite
```

## License

MIT
