---
name: refactoring-decomposer
version: 1.0.0
description: Analyze codebase for size budget violations, decompose god-files and over-budget functions, and generate backwards-compatible shims. Use whenever decomposing complex files, reducing function line counts, or maintaining size budget compliance across packages.
---

# Refactoring Decomposer — Code Hygiene & God-File Decomposition Skill

The `refactoring-decomposer` provides automated analysis, AST inspections, and refactoring guidance to prevent and remediate god-files, over-budget functions (>50 lines), and oversized modules (>500 lines).

## Core Principles

1. **Strict Backwards Compatibility**: Decomposed modules must retain exact public symbols, re-export shims, and docstring contracts. Legacy two-parameter signatures must continue to work.
2. **Architecture Drift Invariant**: Extracted submodules must respect `architecture.yaml` dependency rules. For example, `core` cannot import from `engine` or `config`.
3. **Mechanical Verification**: Every decomposition must be verified by `scripts/check_size_budget.py`, `skills/architecture-drift-guard/scripts/drift_check.py`, and `scripts/verify_tier_a.py`.

## Usage

### Analyze Size Budgets Across Project
```bash
python skills/refactoring-decomposer/scripts/decompose_advisor.py --scan
```

### Scan Specific Subsystem
```bash
python skills/refactoring-decomposer/scripts/decompose_advisor.py --scan --root src/eval_harness
```

## Definition of Done

- Analyzed modules strictly obey the 500-line file ceiling.
- Flagged functions are refactored into focused helpers under 50 lines.
- Architecture drift check and full test suites pass 100% green.
