# Assertion Types Reference

Quick reference for `evals.json` assertion types:

- **exit_zero**: The command under `run` exited with code 0.
- **output_contains**: The combined stdout/stderr of the command under `run` contains the string specified in `contains`.
- **file_contains**: The file at `path` exists and its contents contain the string specified in `contains`.
- **command_exit_zero**: The command specified in `cmd` exited with code 0.
- **file_exists**: The file at `path` exists (does not qualify as a behavioral assertion alone).
