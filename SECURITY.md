# Security Policy

## Supported versions

This is an actively developed monorepo; security fixes land on the default branch
and in the latest release of each package. Older tagged releases are not
maintained — please upgrade to the latest before reporting.

| Package | Supported |
|---|---|
| `langfuse-eval-harness` (root) | latest release + default branch |
| `agent-core`, `behavioral-regression`, `flow-corpus`, `flow-protocol` | latest release + default branch |
| `claude-foundation-tools` | latest release + default branch |

## Reporting a vulnerability

**Please do not open a public issue for security vulnerabilities.**

Report privately through **GitHub Private Vulnerability Reporting**:

1. Go to the repository's **Security** tab → **Report a vulnerability**.
2. Describe the issue, affected package/version, and reproduction steps.

If private reporting is unavailable to you, contact a maintainer listed in
[MAINTAINERS.md](MAINTAINERS.md) to arrange a private channel. Please include
enough detail to reproduce, and give us a reasonable window to remediate before
any public disclosure. We aim to acknowledge reports within a few business days.

## What is in scope

- The code in this repository (the packages above, `scripts/`, and `skills/`).
- Handling of credentials and secrets. This project sources **all** credentials
  from environment variables (see [.env.example](.env.example)) and hard-codes
  none; a finding of a leaked or hard-coded secret is in scope.

## What is out of scope

- Vulnerabilities in **optional** third-party SDKs pulled in only via extras
  (Langfuse, OpenAI, Anthropic, boto3, Arize Phoenix, BrainTrust, autoevals) —
  report those upstream. We will, however, bump pins when a fix is available.
- Findings that require a non-default, explicitly opt-in configuration that the
  documentation warns against.

## Existing security posture

Security is enforced continuously, not just on report:

- **Dependency scanning** — Snyk monitors `requirements.txt`
  (`snyk test` / `snyk monitor`; see the "Security Scanning" section of the
  [README](README.md#security-scanning)).
- **Secret scanning** runs in CI.
- **Eval-integrity guardrails** — evaluation-defining files are protected paths
  requiring reviewed approval, so the meaning of a gate cannot be silently
  weakened (see [CONTRIBUTING.md](CONTRIBUTING.md#protected-paths-require-a-labeled-approval)).

Coordinated disclosure is appreciated; we will credit reporters who wish to be
credited.
