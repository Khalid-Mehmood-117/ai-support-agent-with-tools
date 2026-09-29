"""Action-claim guard: a reply may only claim an action that a tool actually performed.

The model sometimes writes "Creating a support ticket now" or "Your refund has been approved"
without the matching tool call succeeding. This check runs in code on every final reply. If a
reply claims an action whose tool has not succeeded in this conversation, the sentences making the
claim are removed and an honest sentence offering the action is added instead.

This is a code guardrail like the refund policy check; it does not change the prompt.
"""

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ClaimRule:
    kind: str
    tool: str
    patterns: tuple[re.Pattern, ...]
    correction: str


def _compile(*patterns: str) -> tuple[re.Pattern, ...]:
    return tuple(re.compile(p, re.IGNORECASE) for p in patterns)


RULES = [
    ClaimRule(
        kind="refund",
        tool="create_refund",
        patterns=_compile(
            r"\brefund\b[^.!?\n]{0,60}\b(has been|was|is now)\s+(approved|processed|issued|completed|created)\b",
            r"\bI(?:'ve| have)\s+(processed|issued|created|approved)\s+(a|the|your)\s+refund\b",
            r"\bI(?:'ve| have)\s+refunded\b",
            r"\bREF-\d+\b",
        ),
        correction=(
            "I have not created a refund yet. If you would like one, I can check the order's "
            "eligibility and send a refund request for staff approval."
        ),
    ),
    ClaimRule(
        kind="ticket",
        tool="escalate_to_human",
        patterns=_compile(
            r"\bTCK-\d+\b",
            r"\bI(?:'ve| have)\s+(already\s+)?(escalated|created a (support )?ticket|opened a (support )?ticket)\b",
            r"\b(ticket|issue|case|request)\s+(has been|was)\s+(created|escalated|opened|forwarded)\b",
            r"\bI(?:'ll| will| am going to)\s+(escalate|create a (support )?ticket|open a (support )?ticket)"
            r"[^.!?\n]{0,60}\b(now|right away|immediately)\b",
            r"\bcreating a (support )?ticket\b",
        ),
        correction=(
            "I have not created a support ticket yet. Would you like me to create one now so a "
            "specialist can follow up?"
        ),
    ),
    ClaimRule(
        kind="email",
        tool="draft_email",
        patterns=_compile(
            r"\bI(?:'ve| have)\s+(sent|emailed|drafted|prepared)\b[^.!?\n]{0,40}\b(email|summary|draft|message)\b",
            r"\b(email|summary|message)\s+(has been|was)\s+(sent|drafted|prepared)\b",
            r"\bDRF-\d+\b",
        ),
        correction="I have not prepared an email yet. Would you like me to draft one now?",
    ),
]

_SENTENCE_END = re.compile(r"(?<=[.!?])\s+")

# Filler promises such as "Let me do that now." are removed together with a false claim, because
# they announce the same action. They are not claims on their own, so they never trigger the guard.
_ACTION_PROMISE = re.compile(
    r"\blet me (do|handle|take care of|get on) (that|this|it)\b[^.!?\n]{0,30}\b(now|right away|immediately)\b",
    re.IGNORECASE,
)


def unsupported_claims(reply: str, succeeded_tools: set[str]) -> list[str]:
    """Kinds of action the reply claims although the matching tool has not succeeded."""
    return [
        rule.kind for rule in RULES
        if rule.tool not in succeeded_tools and any(p.search(reply) for p in rule.patterns)
    ]


def honest_reply(reply: str, claims: list[str]) -> str:
    """Drop the sentences that make the false claims and add the matching corrections."""
    rules = [rule for rule in RULES if rule.kind in claims]
    kept = [
        sentence for sentence in _SENTENCE_END.split(reply.strip())
        if not _ACTION_PROMISE.search(sentence)
        and not any(p.search(sentence) for rule in rules for p in rule.patterns)
    ]
    return " ".join(kept + [rule.correction for rule in rules]).strip()
