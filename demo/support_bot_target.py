"""A deterministic, offline "support bot" used as the system-under-test in the demo.

This is a stand-in for a real model-backed target. It keyword-routes a support
question to a canned but *actionable* answer, so the eval scores something that
reads like a real answer instead of the question echoed back. It is pure and
offline — no network, no SDK — so every demo run is byte-reproducible.

Wire it into a config as a ``callable`` target::

    target:
      type: callable
      params: { path: "demo.support_bot_target:answer" }

The harness calls ``answer(item.inputs)`` (see ``eval_harness.targets.CallableTarget``),
so the single argument is the item's ``inputs`` dict, e.g. ``{"question": "..."}``.
"""

from __future__ import annotations

# Ordered (substring-set -> answer) routing table. The first rule whose keywords
# all appear in the lowercased question wins. Kept as data, not branches, so the
# routing is easy to read and extend — the same open-closed spirit as the harness.
_ROUTES: tuple[tuple[tuple[str, ...], str], ...] = (
    (
        ("reset", "password"),
        "To reset your password, go to Settings > Security and click "
        '"Reset password". We\'ll email you a secure reset link.',
    ),
    (
        ("password",),
        'You can manage your password under Settings > Security. Use "Reset password" if you\'ve forgotten it.',
    ),
    (
        ("cancel",),
        "You can cancel your plan any time from Settings > Billing > Cancel "
        "plan. Your access continues until the end of the current billing period.",
    ),
    (
        ("refund",),
        "To request a refund, open Settings > Billing > Payment history, select "
        'the charge, and click "Request refund". Refunds post within 5-10 days.',
    ),
    (
        ("invoice",),
        "Your invoices live under Settings > Billing > Payment history, where you can download any invoice as a PDF.",
    ),
    (
        ("upgrade",),
        "To upgrade, go to Settings > Billing > Change plan and pick a higher "
        "tier. The price is prorated for the rest of this billing period.",
    ),
    (
        ("2fa",),
        "Enable two-factor authentication under Settings > Security > "
        "Two-factor authentication, then scan the QR code with your authenticator app.",
    ),
    (
        ("export", "data"),
        "You can export your data from Settings > Privacy > Export data. We'll "
        "email a download link when the export is ready.",
    ),
    (
        ("api", "key"),
        "Create and rotate API keys under Settings > Developer > API keys. Treat "
        "keys like passwords and never commit them to source control.",
    ),
    (
        ("email",),
        "To change the email on your account, go to Settings > Profile, update "
        "the email field, and confirm via the verification link we send.",
    ),
)

# Deliberately unhelpful fallback for questions the bot cannot route. This keeps
# the demo honest: the eval should show the bot is NOT perfect, so the gate and
# the scores mean something.
_FALLBACK = "I'm not sure about that one. Please contact our support team for help."


def answer(inputs: dict | None) -> str:
    """Return a canned support answer for ``inputs['question']``.

    Falls back to a generic "contact support" reply for unrouted questions (and
    for a malformed ``inputs``) so the eval surfaces real quality differences
    rather than always scoring perfectly.
    """
    if not isinstance(inputs, dict):
        return _FALLBACK
    question = str(inputs.get("question", "")).lower()
    for keywords, response in _ROUTES:
        if all(word in question for word in keywords):
            return response
    return _FALLBACK
