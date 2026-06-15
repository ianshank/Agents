---
name: openai-judge
description: LLM-as-a-judge evaluations over OpenAI-compatible APIs (including NVIDIA Nemotron & LM Studio). Use whenever evaluating output quality, correctness, or scoring responses using standard rubrics.
compatibility: python>=3.10
---

# openai-judge — E2E Action Skill

Perform LLM-as-a-judge scoring end to end: take prompt, rubric, and model endpoint, produce score and reasoning, and prove it worked before reporting success.

## 1. Preconditions (input contract)

Confirm these hold before doing anything:
- Target prompt text and grading rubric are present in files.
- OpenAI-compatible model endpoint is reachable (or `--mock` is specified for local-only validation).
- Environment variables or configurations are populated for authentication (e.g. `NVIDIA_API_KEY` for Nemotron).

## 2. Procedure (the E2E steps)

1. Read the input prompt and grading rubric from their target paths.
2. Initialize the OpenAI-compatible client wrapper with model endpoint and api key.
3. Call the completion API with the requested prompt and formatting instructions (preferring JSON output).
4. Extract the verdict JSON containing the score and reasoning.
5. Write `result.json` to the output directory.

Prefer using the execution script:
```bash
python scripts/run.py --model nvidia/nemotron-3-ultra-550b-a55b --prompt prompt.txt --rubric rubric.txt --out result.json
```

## 3. Output contract (postconditions — what "done" means)

- Output file `result.json` is written.
- Output is valid JSON with keys `score` and `reasoning`.
- The score value is a float/integer representing the judgment.

## 4. Failure handling

- On failure, clean up any partial files and raise a clear, descriptive error containing output/logs.
- Gracefully handle JSON parsing errors by returning a structured default failure JSON.

## 5. Validation gate (before declaring success)

You are **not done** until this exits 0:
```bash
python scripts/validate_skill.py --skill . --tier structural,behavioral
```

## 6. Examples

**Example 1**
Input: prompt.txt (What is 2+2?), rubric.txt (Grade answer correctness)
Output: result.json (`{"score": 1.0, "reasoning": "The answer is correct."}`)
