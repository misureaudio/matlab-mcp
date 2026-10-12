"""MATLAB subprocess engine wrapper for batch mode execution."""

import json
import logging
import subprocess
from pathlib import Path
from typing import Any, Optional


logger = logging.getLogger("matlab-mcp-server.engine")


class MATLABEngineWrapper:
    """Wraps MATLAB batch mode execution via subprocess."""

    def __init__(
        self,
        executable: str = "matlab",
        sandbox_dir: Path = None,
        timeout_s: int = 300,
    ):
        # Use absolute paths for all file operations (MATLAB -batch doesn't respect subprocess cwd)
        if sandbox_dir is not None:
            self.sandbox_dir = Path(sandbox_dir).resolve()
        else:
            self.sandbox_dir = Path.cwd().resolve()
        
        self.executable = executable
        self.timeout_s = timeout_s

    def _escape_path_for_matlab(self, path: str) -> str:
        """Escape a Windows path for use in MATLAB commands."""
        return path.replace('\\', '\\\\')

    def execute(self, code: str) -> dict[str, Any]:
        """Execute MATLAB code in batch mode.
        
        Returns structured result with stdout, stderr, exit_code.
        Uses direct -batch execution without wrapper functions for reliability.
        All file operations use absolute paths to work around Windows -batch limitations.
        """
        # User code is passed directly to MATLAB - no escaping needed
        # (code is not wrapped in a string literal, so quotes must be preserved)
        
        # Build the batch command using -batch (works correctly on Windows)
        # Use cd() with absolute path, then execute directly
        safe_sandbox = self._escape_path_for_matlab(str(self.sandbox_dir))
        cmd = [
            self.executable,
            "-nosplash",
            "-nodesktop",
            "-batch",
            f"cd('{safe_sandbox}'); try; {code}; catch ME; fprintf('MATLAB_ERROR: %s\\n', ME.message); exit(1); end; exit(0)",
        ]

        logger.debug(f"Executing MATLAB command: {' '.join(cmd[:4])}...")

        try:
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_s,
                cwd=str(self.sandbox_dir),
            )

            result = {
                "exit_code": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
            }

            if process.returncode != 0:
                logger.warning(f"MATLAB execution failed with code {process.returncode}")
                # Check for MATLAB-specific error in output
                if "MATLAB_ERROR:" in result["stdout"]:
                    result["error"] = True
                    result["matlab_error"] = result["stdout"].split("MATLAB_ERROR:")[1].strip()

            return result

        except subprocess.TimeoutExpired:
            logger.error(f"MATLAB execution timed out after {self.timeout_s}s")
            return {
                "exit_code": -1,
                "error": True,
                "timeout": True,
                "message": f"Execution exceeded timeout of {self.timeout_s} seconds",
            }

    def run_script(self, script_path: str, output_vars: list[str] = None) -> dict[str, Any]:
        """Run a MATLAB .m script and optionally save specified variables.
        
        Args:
            script_path: Path to the .m file (relative to sandbox)
            output_vars: List of variable names to save
            
        Returns:
            Dict with execution result and any saved outputs
        """
        # Build the batch command using -batch (works correctly on Windows)
        safe_sandbox = self._escape_path_for_matlab(str(self.sandbox_dir))
        cmd_parts = [f"cd('{safe_sandbox}');"]
        cmd_parts.append(f"run('{script_path}');")
        
        # If output variables specified, save them to MAT files with absolute paths
        if output_vars:
            for var in output_vars:
                mat_path = self._escape_path_for_matlab(str(self.sandbox_dir / f"{var}.mat"))
                cmd_parts.append(f"if exist('{var}', 'var'), save('{mat_path}', '{var}'); end;")
        
        full_code = "; ".join(cmd_parts) + "; exit(0)"
        
        logger.debug(f"Running MATLAB script: {script_path}")

        try:
            process = subprocess.run(
                [self.executable, "-nosplash", "-nodesktop", "-batch", full_code],
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=self.timeout_s,
                cwd=str(self.sandbox_dir),
            )

            result = {
                "exit_code": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
            }

            if process.returncode != 0:
                logger.warning(f"MATLAB script execution failed with code {process.returncode}")
                # Check for MATLAB-specific error in output
                if "MATLAB_ERROR:" in result["stdout"]:
                    result["error"] = True
                    result["matlab_error"] = result["stdout"].split("MATLAB_ERROR:")[1].strip()

            return result

        except subprocess.TimeoutExpired:
            logger.error(f"MATLAB script execution timed out after {self.timeout_s}s")
            return {
                "exit_code": -1,
                "error": True,
                "timeout": True,
                "message": f"Script execution exceeded timeout of {self.timeout_s} seconds",
            }

    def get_info(self) -> dict[str, Any]:
        """Get MATLAB version and system information."""
        safe_sandbox = self._escape_path_for_matlab(str(self.sandbox_dir))
        cmd = [
            self.executable,
            "-nosplash",
            "-nodesktop",
            "-batch",
            f"cd('{safe_sandbox}'); disp(version); fprintf('%s\\n', computer); fprintf('%s\\n', matlabroot); exit(0)",
        ]

        try:
            process = subprocess.run(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                timeout=30,
                cwd=str(self.sandbox_dir),
            )

            result = {
                "exit_code": process.returncode,
                "stdout": process.stdout.strip(),
                "stderr": process.stderr.strip(),
            }

            # Parse the output (simple extraction)
            lines = result["stdout"].split('\n')
            info = {}
            if len(lines) >= 3:
                info["version"] = lines[0].strip()
                info["platform"] = lines[1].strip()
                info["matlabroot"] = lines[2].strip()

            return {**result, **info}

        except subprocess.TimeoutExpired:
            logger.error("MATLAB info query timed out")
            return {"error": True, "message": "Info query exceeded timeout"}
