"""Wrapper script for MATLAB batch execution."""

% This script is generated dynamically by the MCP server
% It wraps user code with error handling and JSON output

try
    % User code goes here
    evalin('caller', mfilename);
catch ME
    fprintf('MATLAB_ERROR: %s\n', ME.message);
    exit(1);
end
