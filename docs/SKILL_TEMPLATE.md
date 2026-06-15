---
name: {{skill-name}}
description: {{One sentence on what this skill does.}} Use this whenever {{the user asks to <task>, mentions <trigger words>, or needs <outcome>}} — even if they don't say "{{skill-name}}" explicitly.
# compatibility: {{optional — required tools/deps, e.g. "python>=3.10, ffmpeg". Omit if none.}}
---

# {{Skill Name}} — E2E Action Skill

> **This is a template.** Replace every `{{PLACEHOLDER}}`, then validate the result with the
> companion `SKILL_VALIDATION_TEMPLATE.md` (`validate_skill.py`). The frontmatter `name` must
> match the skill's directory name (lowercase-hyphen); the `description` is the *only* triggering
> signal, so make it specific and slightly pushy. This template itself won't pass structural
> validation until you fill the placeholders — that's expected.

Perform **{{the task}}** end to end: take {{inputs}}, produce {{the output artifact}}, and — if
the task produces verifiable artifacts — **prove it worked before reporting success** (§5).

## 1. Preconditions (input contract)

Confirm these hold before doing anything. If any fails, stop and report what's missing — do not improvise around a broken precondition.

- {{Required input present, e.g. "an input file at the path the user gave".}}
- {{Required tool/dependency available, e.g. `command -v ffmpeg`.}}
- {{Any environment/state assumption, e.g. "write access to the output directory".}}

## 2. Procedure (the E2E steps)

Work in imperative steps. Delegate deterministic or repetitive work to bundled scripts in `scripts/` rather than improvising it inline each time — scripts are reproducible and are what the validator runs.

1. {{Step 1 — e.g. "Read and parse the input."}}
2. {{Step 2 — e.g. "Transform / compute / call the tool."}}
3. {{Step 3 — e.g. "Write the output artifact to the agreed path."}}
4. {{Step N — keep going until the task is genuinely finished, not just started.}}

For anything mechanical, prefer a script: `python scripts/run.py --in <input> --out <output>`. Keep
the SKILL.md body under ~500 lines; move long detail to `references/` and point to it here.

## 3. Output contract (postconditions — what "done" means)

Define done as **observable properties**, not as "I did the steps". For artifact-producing skills
this is what the validator checks, so be concrete:

- {{Artifact exists, e.g. "`<output>/result.json` is written".}}
- {{Artifact is well-formed, e.g. "valid JSON with keys `status`, `items`".}}
- {{Behavioral property, e.g. "`status == "ok"` and `len(items) >= 1`".}}
- {{Idempotency, e.g. "re-running over the same input produces the same output".}}

## 4. Failure handling

- **Leave clean state.** On failure, don't leave half-written artifacts. Write to a temp path and move into place only on success, or clean up partial output.
- **Report with evidence.** Say what failed and show the proof (the command, its exit code, the missing file) — never a bare "it didn't work".
- **Idempotent retry.** Running the procedure again from the start must be safe.

## 5. Validation gate (before declaring success)

Choose the gate that matches the skill type — this is the one place a generic template must branch:

**A. Artifact-producing skills** (files, structured output, state changes, fixed workflow steps):
You are **not done** until this exits 0:

```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

A zero exit *is* the definition of done; your own assessment is not. If it fails, fix the cause and
re-run — **do not edit the assertions to make them pass.**

**B. Subjective skills** (writing style, tone, visual design — outputs needing human judgment):
There is no honest scripted gate; assertions on taste manufacture false confidence. Instead:
- Run **structural only** (`python scripts/validate_skill.py --skill . --tier structural`) to keep the metadata/triggering honest.
- Self-check against explicit, concrete criteria: {{list 2-3 observable criteria, e.g. "headline ≤ 8 words", "no passive voice in the summary"}}.
- Use the skill-creator human-review loop for quality — don't fake a behavioral gate.

## 6. Examples

**Example 1**
Input: {{a realistic input the user would give}}
Output: {{the exact artifact produced, and where}}

**Example 2 (edge case)**
Input: {{a tricky/empty/malformed input}}
Output: {{the correct handling — e.g. clear error, no partial artifact}}

---

## Bundled layout

```
{{skill-name}}/
├── SKILL.md                 # this file (frontmatter + body)
├── scripts/
│   ├── run.py               # deterministic task execution (what steps 2–3 call)
│   └── validate_skill.py    # E2E self-check (from SKILL_VALIDATION_TEMPLATE.md)
├── references/              # long detail loaded only when needed
│   └── {{topic}}.md
└── evals/                   # only for artifact-producing skills
    ├── evals.json           # task fixtures + assertions (the output contract, executable)
    └── fixtures/
        └── {{case}}/        # input files + optional setup.py per eval
```

**Why this shape:** metadata (name + description) is always in context; the body loads when the
skill triggers; `references/` and `scripts/` load/execute only as needed (progressive disclosure).
For artifact skills, `evals/` makes the §3 contract executable — which is what lets the validator
turn "looks done" into "is done". Subjective skills can omit `evals/` entirely.
