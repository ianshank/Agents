# Windows / cross-platform gotchas

> The offline suite must pass on Windows as well as Linux CI.

Extracted from `AGENTS.md`: these traps only matter when you are actually running or
writing cross-platform code, so they are loaded on demand rather than every session.
Every one of them was a real bug -- see the CHANGELOG "Windows / cross-platform
portability" entry.

## Known traps

- **`platform.uname()` hangs on some locked-down Windows hosts** (WMI blocked), and Hypothesis calls it at import — so *every* pytest run wedges before collecting a test. `scripts/e2e_shims/sitecustomize.py` neutralizes the hanging `platform._wmi_query`; put `scripts/e2e_shims/` on `PYTHONPATH` when running pytest by hand there (the e2e harness does this automatically).
- **Never send git-plumbing stdin through text mode.** `subprocess.run(..., text=True)` CRLF-translates `\n`→`\r\n` on Windows, which corrupts `mktree`/`hash-object` input (a tree entry name became `<file>\r`). Use byte I/O — see `agent_core.store_sync._run`.
- **Emit path/finding strings with `.as_posix()`**, not OS-native separators, so output is deterministic across platforms.
- **Keep eval commands and generated YAML free of Windows `\` paths and POSIX-only shell** (`/dev/null`, `test $? -eq 1`, pipes). `validate_skill.py` rewrites a standalone `python` token to `sys.executable`; write `command_exit_zero` evals as cross-platform python one-liners.
- **WSL bash cannot execute scripts at Windows paths.** `shutil.which("bash")`
  finds `C:\WINDOWS\system32\bash.EXE` (the WSL shim), which accepts `bash -c
  'echo ok'` but returns exit 127 when handed a Windows-native temp path.
  Skill tests that shell out to bash use a `_bash_works()` probe (creates a
  real temp `.sh` file and verifies execution) rather than a simple `BASH is
  not None` check.
- **Symlinks require elevation on Windows.** `Path.symlink_to()` raises
  `OSError` / `WinError 1314` unless the user has `SeCreateSymbolicLinkPrivilege`.
  Tests guarded by `_can_symlink()`.
