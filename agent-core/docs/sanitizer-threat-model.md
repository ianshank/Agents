# Sanitizer Threat Model

## Adversary Model

The `RuleSanitizer` is a **defence-in-depth** layer for blocking well-known prompt-injection
patterns in raw text inputs *before* they are ingested as claim IDs. It is not a complete
security boundary.

Adversary: an attacker who controls one or more of the raw input strings passed to
`build_sanitized_claims`. Goal: cause the downstream LLM-backed verifier to deviate from
its instructions.

## Covered Injection Classes

| Category | Rule IDs | Description |
|---|---|---|
| `instruction_override` | io-01–io-04 | Direct commands to ignore/disregard/forget prior instructions |
| `role_hijack` | rh-01–rh-04 | Commands to assume a different persona or role |
| `delimiter_injection` | di-01–di-04 | Fake system-message delimiters (`<\|system\|>`, `[SYSTEM]`, etc.) |
| `exfiltration` | ex-01–ex-03 | Commands to reveal configuration, secrets, or system prompts |
| `prompt_leak` | pl-01–pl-03 | Requests to repeat or show the original system prompt |

## Explicit Non-Goals / Known Bypasses

The following attack forms are **NOT** detected and are documented as out-of-scope:

1. **Zero-width / invisible character interleaving** — e.g. `ign​ore` (zero-width space).
   Normalisation would require Unicode NFKC + invisible-char stripping, not in scope.
2. **Base64 / URL / ROT13 / other encoding** — encoded payloads that decode to instructions.
   Content decoding is not attempted.
3. **Homoglyph substitution** — Cyrillic 'а' for Latin 'a', etc. Visual similarity attacks.
4. **Novel phrasing** — paraphrase attacks outside the known rule patterns.
5. **Multilingual attacks** — non-English injection strings.
6. **Semantic attacks** — instructions embedded in seemingly benign narratives that require
   understanding to detect.

The regex filter should be treated as a first pass that catches copy-paste attacks and
well-known patterns from public jailbreak databases. It does NOT replace:
- Prompt-level defences (system prompt hardening)
- Output monitoring
- LLM fine-tuning for instruction-following robustness
