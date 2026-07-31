# Skill Validator — E2E

A skill is "done" only when it produces the right artifacts on real inputs — not when its author
says so. Two tiers:

| Tier | Checks | Side effects | When |
|------|--------|--------------|------|
| `structural` | frontmatter parses; `name` valid + matches dir; `description` present and triggers well; SKILL.md not oversized; `run`/`setup` scripts referenced by evals exist | none | every commit / pre-merge |
| `behavioral` | runs each eval's task E2E, asserts the output contract against real artifacts; emits `grading.json` | runs the skill's commands under `.skill-validation/` | before "done"; nightly / trusted branches |

**What the validator enforces, honestly:** it rejects evals that execute nothing, evals with no
assertions, and evals whose only checks are `file_exists` (existence ≠ correctness). It **cannot**
tell whether your assertions are *meaningful* — `command_exit_zero: "true"` passes forever. Assertion
quality is the irreducible ground truth; review assertions the way you'd review a `validation_command`.
A check that can't fail is worse than no check, because it manufactures confidence.

---

## 1. `evals/evals.json` — the executable output contract

Each eval is one realistic task. `run` executes the skill end to end; `assertions` are the §3 output
contract from `SKILL_TEMPLATE.md`, made checkable. Field convention: **`text` is always the human
label; the search payload is `contains`** (no overloaded keys).

```json
{
  "skill": "{{skill-name}}",
  "evals": [
    {
      "id": "happy-path",
      "prompt": "{{what a real user would ask}}",
      "setup": "python evals/fixtures/happy-path/setup.py",
      "run": "python scripts/run.py --in evals/fixtures/happy-path/input --out .skill-validation/happy",
      "assertions": [
        { "type": "exit_zero", "text": "task command succeeds" },
        { "type": "command_exit_zero", "cmd": "python -m json.tool .skill-validation/happy/result.json", "text": "result is valid JSON" },
        { "type": "file_contains", "path": ".skill-validation/happy/result.json", "contains": "\"status\": \"ok\"", "text": "status is ok" }
      ]
    },
    {
      "id": "empty-input",
      "prompt": "{{edge case: malformed or empty input}}",
      "run": "python scripts/run.py --in evals/fixtures/empty/input --out .skill-validation/empty",
      "assertions": [
        { "type": "output_contains", "contains": "no records", "text": "fails loudly, not silently" }
      ]
    }
  ]
}
```

### Assertion types

| `type` | Fields (besides `text`) | Passes when | Behavioral? |
|--------|-------------------------|-------------|-------------|
| `exit_zero` | — | the eval's `run` command exited 0 (fails if there is no `run`) | yes |
| `exit_nonzero` | — | the eval's `run` command exited non-zero (fails if there is no `run`) | yes |
| `idempotent` | — | running the `run` command a second time yields identical stdout/stderr (fails if no `run` or second run exits non-zero) | yes |
| `output_contains` | `contains` | `run` stdout+stderr contains the payload (fails if no `run`) | yes |
| `file_contains` | `path`, `contains` | file exists and contains the payload | yes |
| `command_exit_zero` | `cmd` | `cmd` (run in the skill dir) exits 0 | yes |
| `file_exists` | `path` | file exists — existence only, does **not** satisfy the behavioral requirement | no |

Rules the validator enforces per eval: at least one assertion; something actually executes (a `run`
or a `command_exit_zero`); and at least one *behavioral* assertion. Write outputs under
`.skill-validation/` (git-ignore it) so the skill dir stays clean and evals don't see each other's
leftovers.
