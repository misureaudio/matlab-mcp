"""Tool definitions for MATLAB execution."""

from pathlib import Path
from typing import Any

from fastmcp import FastMCP


def register(server: FastMCP, matlab_engine) -> None:
    """Register execution-related tools with the MCP server."""

    @server.tool()
    def matlab_execute(
        code: str,
        timeout_s: int = 300,
    ) -> str:
        """Execute MATLAB code in batch mode.
        
        Use for one-off calculations, data processing, or generating outputs.
        
        Args:
            code: MATLAB code to execute (single line or semicolon-separated statements)
            timeout_s: Maximum execution time in seconds (default: 300)
            
        Returns:
            JSON string with exit_code, stdout, stderr, and optional error details
        """
        matlab_engine.timeout_s = timeout_s
        result = matlab_engine.execute(code)
        
        import json
        return json.dumps(result, indent=2, default=str)

    @server.tool()
    def matlab_run_script(
        script_path: str,
        output_vars: list[str] | None = None,
    ) -> str:
        """Execute a MATLAB .m script file with optional variable output.
        
        The script must exist in the sandbox directory.
        
        Args:
            script_path: Path to the .m file (relative to sandbox)
            output_vars: List of variable names to save as MAT files
            
        Returns:
            JSON string with execution result and any saved outputs
        """
        # Build code that runs the script and optionally saves variables
        escaped_script = script_path.replace("'", "''")
        code_parts = [f"run('{escaped_script}');"]
        
        if output_vars:
            for var in output_vars:
                safe_var = var.replace("'", "''")
                code_parts.append(f"if exist('{safe_var}', 'var'), save('{safe_var}.mat', '{safe_var}'); end;")
        
        full_code = "; ".join(code_parts)
        result = matlab_engine.execute(full_code)
        
        # Try to load any saved MAT files as JSON
        import json
        if result.get("exit_code") == 0 and output_vars:
            outputs = {}
            for var in output_vars:
                mat_file = matlab_engine.sandbox_dir / f"{var}.mat"
                if mat_file.exists():
                    # Note: MAT files can't be read directly by Python without scipy.io
                    # We'll note their existence but not load them
                    outputs[var] = {"saved_as": f"{var}.mat", "note": "MAT file saved - use MATLAB to read"}
                    mat_file.unlink()  # Clean up
            
            if outputs:
                result["outputs"] = outputs
        
        return json.dumps(result, indent=2, default=str)
