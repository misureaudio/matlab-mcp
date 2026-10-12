"""Tests for the MATLAB MCP server engine."""

import pytest
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from engine.engine_wrapper import MATLABEngineWrapper
from engine.sandbox import SandboxManager


@pytest.fixture
def sandbox(tmp_path):
    """Create a temporary sandbox directory."""
    sandbox_dir = tmp_path / "matlab-sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return SandboxManager(sandbox_dir)


@pytest.fixture
def engine(tmp_path):
    """Create a MATLAB engine wrapper with temp sandbox."""
    sandbox_dir = tmp_path / "matlab-sandbox"
    sandbox_dir.mkdir(parents=True, exist_ok=True)
    return MATLABEngineWrapper(
        executable="matlab",
        sandbox_dir=sandbox_dir,
        timeout_s=30,
    )


class TestSandboxManager:
    """Tests for SandboxManager."""

    def test_ensure_exists(self, tmp_path):
        """Test that ensure_exists creates the directory."""
        sandbox_dir = tmp_path / "new-sandbox"
        manager = SandboxManager(sandbox_dir)
        assert not sandbox_dir.exists()
        manager.ensure_exists()
        assert sandbox_dir.exists()
        assert sandbox_dir.is_dir()

    def test_ensure_exists_idempotent(self, tmp_path):
        """Test that ensure_exists is idempotent."""
        sandbox_dir = tmp_path / "sandbox"
        manager = SandboxManager(sandbox_dir)
        manager.ensure_exists()
        manager.ensure_exists()  # Should not raise
        assert sandbox_dir.exists()

    def test_resolve_path_valid(self, sandbox, tmp_path):
        """Test resolving a valid path within sandbox."""
        # Create a file in sandbox
        test_file = sandbox.base_dir / "test.txt"
        test_file.write_text("hello")
        
        resolved = sandbox.resolve_path("test.txt")
        assert resolved == test_file
        assert str(resolved).startswith(str(sandbox.base_dir))

    def test_resolve_path_traversal_blocked(self, sandbox):
        """Test that path traversal is blocked."""
        with pytest.raises(ValueError):
            sandbox.resolve_path("../outside.txt")

    def test_resolve_path_absolute_outside(self, sandbox, tmp_path):
        """Test that absolute paths outside sandbox are blocked."""
        outside = tmp_path / "outside.txt"
        with pytest.raises(ValueError):
            sandbox.resolve_path(str(outside))


class TestEngineWrapper:
    """Tests for MATLABEngineWrapper."""

    def test_get_info(self, engine):
        """Test getting MATLAB version info."""
        result = engine.get_info()
        assert result["exit_code"] == 0
        assert "version" in result
        assert "platform" in result
        assert "matlabroot" in result

    def test_simple_calculation(self, engine):
        """Test simple MATLAB calculation."""
        result = engine.execute("disp(2 + 3);")
        assert result["exit_code"] == 0
        assert "5" in result["stdout"]

    def test_array_operation(self, engine):
        """Test MATLAB array operation."""
        result = engine.execute("x = 1:5; disp(sum(x));")
        assert result["exit_code"] == 0
        assert "15" in result["stdout"]

    def test_save_variable(self, engine):
        """Test saving a variable to .mat file."""
        result = engine.execute("x = [1 2 3]; save('test.mat', 'x');")
        assert result["exit_code"] == 0
        # Verify file was created
        mat_file = engine.sandbox_dir / "test.mat"
        assert mat_file.exists()
        assert mat_file.stat().st_size > 0

    def test_load_variable(self, engine):
        """Test loading a variable from .mat file."""
        # First save
        engine.execute("x = 42; save('loadtest.mat', 'x');")
        # Then load and display
        result = engine.execute("load('loadtest.mat'); disp(x);")
        assert result["exit_code"] == 0
        assert "42" in result["stdout"]

    def test_error_handling(self, engine):
        """Test that MATLAB errors are captured."""
        result = engine.execute("disp(1/0);")
        # Division by zero should produce Inf, not an error
        assert result["exit_code"] == 0
        assert "Inf" in result["stdout"]

    def test_syntax_error(self, engine):
        """Test that syntax errors are captured."""
        result = engine.execute("this is not valid matlab code")
        assert result["exit_code"] != 0
        assert result.get("error") is True

    def test_run_script(self, engine, tmp_path):
        """Test running a MATLAB script."""
        # Create a test script
        script = engine.sandbox_dir / "test_script.m"
        script.write_text("x = 10; disp(x);")
        
        result = engine.run_script("test_script.m")
        assert result["exit_code"] == 0
        assert "10" in result["stdout"]

    def test_run_script_with_output(self, engine):
        """Test running a script with output variables."""
        script = engine.sandbox_dir / "output_script.m"
        script.write_text("result = 99; status = 'ok';")
        
        result = engine.run_script("output_script.m", output_vars=["result", "status"])
        assert result["exit_code"] == 0
        # Verify .mat files were created
        assert (engine.sandbox_dir / "result.mat").exists()
        assert (engine.sandbox_dir / "status.mat").exists()

    def test_complex_numbers(self, engine):
        """Test complex number operations."""
        result = engine.execute("z = 1 + 2i; disp(real(z)); disp(imag(z));")
        assert result["exit_code"] == 0
        assert "1" in result["stdout"]
        assert "2" in result["stdout"]


class TestEngineWrapperPathEscaping:
    """Tests for path escaping in engine wrapper."""

    def test_escape_path_windows(self, tmp_path):
        """Test path escaping for Windows paths."""
        sandbox_dir = tmp_path / "sandbox"
        engine = MATLABEngineWrapper(
            executable="matlab",
            sandbox_dir=sandbox_dir,
            timeout_s=30,
        )
        escaped = engine._escape_path_for_matlab(str(sandbox_dir))
        # Backslashes should be doubled
        if "\\" in str(sandbox_dir):
            assert "\\\\" in escaped


class TestMCPIntegration:
    """Integration tests for MCP server components."""

    def test_server_creation(self):
        """Test that MCP server can be created."""
        from fastmcp import FastMCP
        server = FastMCP("test-server")
        assert server is not None

    def test_tool_registration(self, engine, sandbox):
        """Test that tools can be registered."""
        from fastmcp import FastMCP
        from tools import execute, files, info
        
        server = FastMCP("test-server")
        execute.register(server, engine)
        files.register(server, sandbox)
        info.register(server, engine)
        
        # Verify tools are registered
        import asyncio
        tools = asyncio.run(server._list_tools())
        tool_names = [t.name for t in tools]
        
        assert "matlab_execute" in tool_names
        assert "matlab_run_script" in tool_names
        assert "matlab_upload_file" in tool_names
        assert "matlab_download_file" in tool_names
        assert "matlab_list_files" in tool_names
        assert "matlab_info" in tool_names
        assert "matlab_diagnose" in tool_names
