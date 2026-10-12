"""Tool definitions for file management."""

import base64
from pathlib import Path

from fastmcp import FastMCP


def register(server: FastMCP, sandbox) -> None:
    """Register file-related tools with the MCP server."""

    @server.tool()
    def matlab_upload_file(
        content_base64: str,
        filename: str,
    ) -> str:
        """Upload a file to the MATLAB sandbox directory.
        
        The file will be available for MATLAB scripts to read.
        
        Args:
            content_base64: Base64-encoded content of the file
            filename: Target filename in sandbox (e.g., 'data.csv')
            
        Returns:
            Success or error message as string
        """
        try:
            # Decode and save file
            content = base64.b64decode(content_base64)
            filepath = sandbox.resolve_path(filename)
            
            # Check size limit (100MB default)
            if len(content) > 100 * 1024 * 1024:
                return "Error: File exceeds maximum size of 100MB"
            
            filepath.write_bytes(content)
            return f"File uploaded successfully to {filepath}"
        except Exception as e:
            return f"Upload failed: {str(e)}"

    @server.tool()
    def matlab_download_file(
        filename: str,
    ) -> str:
        """Download a file from the MATLAB sandbox directory.
        
        Returns base64-encoded content along with metadata.
        
        Args:
            filename: Filename in sandbox to download
            
        Returns:
            String containing filename, size_bytes, and base64_content
        """
        try:
            filepath = sandbox.resolve_path(filename)
            
            if not filepath.exists():
                return f"Error: File '{filename}' not found"
            
            # Check size limit
            file_size_mb = sandbox.get_size_mb(filepath)
            if file_size_mb > 100:
                return f"Error: File too large ({file_size_mb:.1f}MB, max 100MB)"
            
            content_b64 = base64.b64encode(filepath.read_bytes()).decode('ascii')
            return (
                f"filename={filename}\n"
                f"size_bytes={filepath.stat().st_size}\n"
                f"base64_content={content_b64}"
            )
        except Exception as e:
            return f"Download failed: {str(e)}"

    @server.tool()
    def matlab_list_files(
        pattern: str = "*",
    ) -> str:
        """List files available in the MATLAB sandbox directory.
        
        Optional glob pattern for filtering.
        
        Args:
            pattern: Glob pattern to filter files (default: '*')
            
        Returns:
            String listing filenames with sizes, or 'No files found' message
        """
        try:
            files = sandbox.list_files(pattern)
            if not files:
                return "No files found matching pattern"
            
            file_info = []
            for fname in sorted(files):
                fpath = sandbox.base_dir / fname
                size_kb = fpath.stat().st_size / 1024
                file_info.append(f"{fname} ({size_kb:.1f}KB)")
            
            return "\n".join(file_info)
        except Exception as e:
            return f"List failed: {str(e)}"
