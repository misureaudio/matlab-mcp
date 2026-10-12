"""Tool definitions for MATLAB information and diagnostics."""

from fastmcp import FastMCP


def register(server: FastMCP, matlab_engine) -> None:
    """Register information-related tools with the MCP server."""

    @server.tool()
    def matlab_info() -> str:
        """Return MATLAB version, platform, and installation information.
        
        Useful for verifying MATLAB is accessible before running commands.
        
        Returns:
            JSON string with version, platform, and matlabroot fields
        """
        try:
            info = matlab_engine.get_info()
            import json
            return json.dumps(info, indent=2, default=str)
        except Exception as e:
            return f"Error getting MATLAB info: {str(e)}"

    @server.tool()
    def matlab_diagnose(
        toolboxes: list[str] | None = None,
    ) -> str:
        """Run diagnostic checks on MATLAB environment.
        
        Optionally check specific toolbox availability.
        
        Args:
            toolboxes: List of toolbox names to check (e.g., ['Signal Processing', 'Statistics'])
            
        Returns:
            String with toolbox status results and version info
        """
        # Build diagnostic code
        code_parts = []
        
        if toolboxes:
            for tb in toolboxes:
                code_parts.append(
                    f"fprintf('Checking toolbox: {tb}... ');"
                )
                code_parts.append(
                    f"if exist('{tb}', 'dir') > 0;"
                )
                code_parts.append(
                    f"    fprintf('AVAILABLE\\n');"
                )
                code_parts.append(
                    f"else;"
                )
                code_parts.append(
                    f"    fprintf('NOT FOUND\\n');"
                )
                code_parts.append(f"end")
        else:
            # Check all common toolboxes
            common_toolboxes = [
                "Signal Processing", "Statistics and Machine Learning",
                "Image Processing", "Control System", "Simulink",
                "Curve Fitting", "Optimization", "Deep Learning"
            ]
            for tb in common_toolboxes:
                code_parts.append(
                    f"fprintf('Checking toolbox: {tb}... ');"
                )
                code_parts.append(
                    f"if exist('{tb}', 'dir') > 0;"
                )
                code_parts.append(
                    f"    fprintf('AVAILABLE\\n');"
                )
                code_parts.append(
                    f"else;"
                )
                code_parts.append(
                    f"    fprintf('NOT FOUND\\n');"
                )
                code_parts.append(f"end")

        result = matlab_engine.execute("\n".join(code_parts))
        
        # Add basic info
        try:
            version_info = matlab_engine.get_info()
            result["version"] = version_info.get("version", "unknown")
        except Exception:
            pass
        
        import json
        return json.dumps(result, indent=2, default=str)
