Deliberately empty of a `Makefile`. Used by the `no-makefile-fails-closed` eval to
confirm `run_pre_pr_gate.py` fails closed (non-zero exit, `"passed": false` in its
report) when `make` itself cannot find a target to run, instead of silently
reporting success.
