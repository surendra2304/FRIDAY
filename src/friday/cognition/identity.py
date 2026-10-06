"""Who the owner is, decided by identity rather than by exclusion.

Authority over FRIDAY's own code was previously granted by a **deny-list of agent
names**: anything not on the list was treated as the owner. That admits every name
nobody remembered to add — an agent introduced tomorrow, or simply any string a
caller chooses — and the comment above the list claimed the opposite of what it
did (BUG-011 in the Phase 0-2 audit).

Approval and mandate issuance are human acts, so the rule is inverted here: an
actor carries owner authority only by being the configured owner (``FRIDAY_USER_NAME``,
or whatever the running configuration says the user is called) or the literal word
``owner``. Membership of the agent namespace is a second, independent refusal —
kept because an agent that renames itself to the owner's name must still not pass.
"""

from __future__ import annotations

import os

#: Names that belong to agents, never to the owner. This is a refusal that runs
#: *after* the positive check: it can only take authority away, never grant it.
AGENT_NAMESPACE = frozenset(
    {
        "",
        "friday",
        "forge",
        "sentinel",
        "inference",
        "memora",
        "stratex",
        "intelx",
        "futuris",
        "cortex",
        "system",
        "bot",
        "agent",
        "automation",
        "self",
    }
)


def _identity_part(actor: str) -> str:
    """The name itself, without a role suffix such as ``(CLI)`` or ``(standing mandate …)``."""
    text = (actor or "").strip()
    if " (" in text and text.endswith(")"):
        text = text.split(" (", 1)[0].strip()
    return text


def configured_owner_name() -> str:
    """The owner's configured name, from the one source the running code uses.

    Settings first, because that is what the CLI and the API read when they decide
    what to call the owner; the environment variable is the fallback for a machine
    where settings cannot be loaded. Reading the environment first looked
    equivalent and was not: settings are cached for the life of the process, so a
    name changed after the first read produced two different answers to "who is the
    owner", and the CLI could be refused for approving as somebody it had just
    called the owner.
    """
    try:
        from friday.core.config import get_settings

        name = (get_settings().user_name or "").strip()
        if name:
            return name
    except Exception:  # a configuration that cannot load falls through to the env
        pass
    return os.getenv("FRIDAY_USER_NAME", "").strip()


def is_agent_namespace(actor: str) -> bool:
    """True when the actor names an agent (or names nothing at all)."""
    return _identity_part(actor).lower() in AGENT_NAMESPACE


def is_owner_identity(actor: str) -> bool:
    """True only for the positively identified owner.

    ``owner`` is always accepted, which is what an operator who never set a name
    will be called; otherwise the actor must equal the configured user name. An
    agent name is refused even if it happens to match, because an agent holding
    the owner's name is still an agent.
    """
    name = _identity_part(actor).lower()
    if not name or name in AGENT_NAMESPACE:
        return False
    if name == "owner":
        return True
    configured = configured_owner_name().lower()
    return bool(configured) and name == configured
