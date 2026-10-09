"""Readings: numbers that know whether they were measured.

The pattern this replaces, found in every consumer of the ecosystem status:

    risk.get("aggregate_leverage", 0.85)

That default is a fabricated measurement. When the trading bridge is not
connected, no key is present, and the caller states ``0.85x leverage`` - a
specific, plausible, entirely invented number - in a dashboard, a briefing, or
out loud in FRIDAY's voice. The same shape appeared with ``14.5`` for loss
proximity, ``54.0`` for concentration, ``0.84`` for model confidence and
``420.50`` for P&L. Each one was chosen because it looked reasonable, which is
precisely what makes it undetectable: a reader cannot tell an invented 0.85x
from a measured one.

Two failure modes follow from the same root, and both are handled here:

1. **The invented default.** ``read_number(mapping, key)`` returns ``None`` when
   the key is absent, ``None``, or unparseable. Callers are forced to decide what
   to say about missing data instead of being silently handed a number.
2. **The explicit-None trap.** ``mapping.get(key, default)`` does *not* return
   the default when the key exists with the value ``None``. A schema change that
   started reporting unknown channels as ``None`` therefore crashed a vigilance
   loop doing ``if proximity >= 70.0`` (``TypeError: '>=' not supported between
   instances of 'NoneType' and 'float'``) - the loop had no concept of "no
   reading". :class:`Reading` makes unknown a first-class state that callers
   must branch on.

The rule for anything user-facing: an unknown value is reported as unknown, in
the same sentence that would otherwise have carried the invented number.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping

__all__ = [
    "Reading",
    "read_number",
    "read_text",
    "describe",
    "format_money",
    "format_number",
    "UNKNOWN_LABEL",
]

#: What every surface says when a value was never measured. One string, so a
#: change of wording happens in one place, and so a test can assert on it.
UNKNOWN_LABEL = "unknown (no reading)"


def _coerce_number(value: Any) -> float | None:
    """Return *value* as a float, or ``None`` if it is not one."""
    if value is None or isinstance(value, bool):
        # ``bool`` is an ``int`` subclass; True as a measurement is a bug, not a 1.
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except (TypeError, ValueError):
            return None
    return None


@dataclass(frozen=True)
class Reading:
    """A value that may not have been measured.

    ``value`` is ``None`` exactly when nothing was reported. There is no default
    number anywhere in this class: constructing a ``Reading`` cannot invent one.
    """

    value: float | None
    source: str = ""
    reported_at: str = ""

    @property
    def known(self) -> bool:
        return self.value is not None

    def or_else(self, fallback: float) -> float:
        """A number for arithmetic that cannot do without one.

        Named ``or_else`` rather than ``default`` so a call site reads as a
        deliberate substitution. Every caller that uses this in user-facing text
        must also say that the value is a fallback; the alternative is the bug
        this module exists to prevent.
        """
        return self.value if self.value is not None else float(fallback)

    def percent(self, digits: int = 1) -> str:
        return f"{self.value:.{digits}f}%" if self.known else UNKNOWN_LABEL

    def number(self, digits: int = 2, suffix: str = "") -> str:
        if not self.known:
            return UNKNOWN_LABEL
        return f"{self.value:.{digits}f}{suffix}"

    def currency(self, symbol: str = "$", digits: int = 2) -> str:
        if not self.known:
            return UNKNOWN_LABEL
        sign = "-" if self.value < 0 else ""
        return f"{sign}{symbol}{abs(self.value):,.{digits}f}"

    def at_least(self, threshold: float) -> bool:
        """``True`` only when a reading exists and clears *threshold*.

        Unknown is not "above" and not "below": callers asking this question want
        a safety answer, and the only safe answer about an unmeasured value is
        "not confirmed".
        """
        return self.known and self.value >= threshold  # type: ignore[operator]

    def text(self, template: str = "{value}") -> str:
        return UNKNOWN_LABEL if not self.known else template.format(value=self.value)


def read_number(
    mapping: Mapping[str, Any] | None,
    key: str,
    *,
    source: str = "",
) -> Reading:
    """Read ``key`` from ``mapping`` as a :class:`Reading`.

    Absent, ``None``, and non-numeric all produce an unknown ``Reading``. A
    reported ``0`` is a real measurement of zero and stays known - the difference
    between "the portfolio is flat" and "nobody told me the portfolio's value" is
    the whole point.
    """
    if not mapping:
        return Reading(None, source=source or "no data source")
    return Reading(
        _coerce_number(mapping.get(key)),
        source=source or str(mapping.get("source", "")) or "",
        reported_at=str(mapping.get("reported_at", "") or ""),
    )


def read_text(mapping: Mapping[str, Any] | None, key: str, *, unknown: str = UNKNOWN_LABEL) -> str:
    """Read a string field, or ``unknown`` when it is absent or blank."""
    if not mapping:
        return unknown
    value = mapping.get(key)
    if value is None:
        return unknown
    text = str(value).strip()
    return text or unknown


def format_money(value: Any, symbol: str = "$", digits: int = 2) -> str:
    """Format a possibly-absent money value, or say it is unknown.

    For the many call sites that hold a bare float-or-None out of a dataclass
    (``risk.total_exposure_usdt``) rather than a mapping. ``None`` must never be
    rendered as ``0.00`` or as a plausible-looking number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNKNOWN_LABEL
    return f"{symbol}{value:,.{digits}f}"


def format_number(value: Any, digits: int = 2, suffix: str = "") -> str:
    """Format a possibly-absent number, or say it is unknown."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return UNKNOWN_LABEL
    return f"{value:,.{digits}f}{suffix}"


def describe(reading: Reading, what: str) -> str:
    """A sentence fragment for a human, never a bare number."""
    if not reading.known:
        return f"{what}: {UNKNOWN_LABEL}"
    return f"{what}: {reading.number()}"
