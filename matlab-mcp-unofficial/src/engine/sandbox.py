"""Sandbox directory management for MATLAB workspace."""

import logging
from pathlib import Path


logger = logging.getLogger("matlab-mcp-server.sandbox")


class SandboxManager:
    """Manages a sandbox directory where MATLAB operates."""

    def __init__(self, base_dir: Path):
        self.base_dir = Path(base_dir)

    def ensure_exists(self) -> None:
        """Create the sandbox directory if it doesn't exist."""
        self.base_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"Sandbox directory ensured at {self.base_dir}")

    def resolve_path(self, filename: str) -> Path:
        """Resolve a filename to an absolute path within the sandbox.
        
        Prevents directory traversal attacks by canonicalizing paths.
        """
        # Sanitize: only allow alphanumeric, hyphens, underscores, dots
        if not all(c.isalnum() or c in "-_. " for c in filename):
            raise ValueError(f"Invalid filename characters: {filename}")

        full_path = (self.base_dir / filename).resolve()

        # Security check: ensure path stays within sandbox
        try:
            full_path.relative_to(self.base_dir.resolve())
        except ValueError:
            raise ValueError(
                f"Path traversal detected: {filename} resolves outside sandbox"
            )

        return full_path

    def list_files(self, pattern: str = "*") -> list[str]:
        """List files in the sandbox directory matching a glob pattern."""
        return [f.name for f in self.base_dir.glob(pattern) if f.is_file()]

    def get_size_mb(self, path: Path) -> float:
        """Get file size in megabytes."""
        return path.stat().st_size / (1024 * 1024)
