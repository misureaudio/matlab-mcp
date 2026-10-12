"""MATLAB MCP Server — entry point."""

import argparse
import logging
import sys
import tempfile
from pathlib import Path

import yaml
from fastmcp import FastMCP

from engine.sandbox import SandboxManager
from engine.engine_wrapper import MATLABEngineWrapper


# Fallback configuration used when no config.yaml is found (e.g. after
# `pip install`, where the project-root config.yaml is not shipped).
DEFAULT_CONFIG = {
    "matlab": {
        "executable": "matlab",  # resolved via PATH
        "default_timeout_s": 300,
    },
    "paths": {
        "sandbox_dir": str(Path(tempfile.gettempdir()) / "matlab-sandbox"),
    },
}


def setup_logging(level: str = "INFO") -> None:
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


def load_config(config_path: Path) -> dict:
    """Load configuration from YAML file."""
    with open(config_path, 'r') as f:
        return yaml.safe_load(f)


def main() -> None:
    parser = argparse.ArgumentParser(description="MATLAB MCP Server")
    parser.add_argument("--config", type=Path, default=None, help="Config file path")
    args = parser.parse_args()

    setup_logging("INFO")
    logger = logging.getLogger("matlab-mcp-server")

    # Add src directory to sys.path for imports (dev layout: src/server.py
    # with engine/ and tools/ siblings; installed layout: already on path)
    src_dir = str(Path(__file__).resolve().parent)
    if src_dir not in sys.path:
        sys.path.insert(0, src_dir)

    # Load config: explicit --config > project-root config.yaml (dev layout)
    # > built-in defaults (installed layout)
    config_path = args.config
    if config_path is None:
        candidate = Path(__file__).resolve().parent.parent / "config.yaml"
        if candidate.is_file():
            config_path = candidate

    if config_path is not None:
        config = load_config(config_path)
        logger.info(f"Loaded config from {config_path}")
    else:
        config = DEFAULT_CONFIG
        logger.warning(
            "No config.yaml found; using built-in defaults "
            "(matlab from PATH, sandbox in temp dir). Pass --config for full control."
        )

    sandbox_dir = Path(config["paths"]["sandbox_dir"])
    matlab_executable = config["matlab"]["executable"]
    default_timeout_s = config["matlab"]["default_timeout_s"]

    # Initialize components
    sandbox = SandboxManager(sandbox_dir)
    sandbox.ensure_exists()

    matlab_engine = MATLABEngineWrapper(
        executable=matlab_executable,
        sandbox_dir=sandbox_dir,
        timeout_s=default_timeout_s,
    )

    # Create MCP server using fastmcp
    server = FastMCP("matlab-mcp-server")

    # Register tools from modules
    from tools import execute, files, info
    
    execute.register(server, matlab_engine)
    files.register(server, sandbox)
    info.register(server, matlab_engine)

    logger.info("Starting MATLAB MCP server on stdio transport")
    
    try:
        server.run(transport="stdio")
    except KeyboardInterrupt:
        logger.info("Server stopped by user")


if __name__ == "__main__":
    main()
