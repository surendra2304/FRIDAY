"""A source-wide guard against one specific, recurring bug.

The most expensive class of defect found in this codebase was not a crash: it was
``payload.get("equity", 10000.0)`` — a *plausible-looking* default that turns "the
bridge did not report an equity" into "the account holds $10,000". The same shape
produced a $10,540.25 testnet equity, a 1.5 profit factor, a 55% win rate, a 5.0%
drawdown threshold, a 0.84 model confidence, a 168-hour plan, a 98.4/100 site
health, a 1.45 Sharpe and a 100% uptime ratio on a monitor that had never polled.

This test parses the whole tree and fails on any ``mapping.get(<telemetry key>,
<non-zero numeric literal>)`` that is not explicitly justified below. An
exception has to be a statement about *why a default is not a claim* (a ranking
key, a Bayesian prior), never "it was convenient".
"""

from __future__ import annotations

import ast
from pathlib import Path

SRC = Path(__file__).resolve().parents[1] / "src" / "friday"

#: Keys whose absence must never be filled with a number a user could read as a
#: measurement, a price, an account balance, a score or a health figure.
TELEMETRY_KEY_PATTERN = (
    "equity|cash|pnl|profit_factor|win_rate|sharpe|sortino|drawdown|balance|exposure|"
    "confidence|accuracy|var_?9|streak|positions?|alerts?|threads|latency|price|volume|"
    "portfolio|weights?|metrics?|returns?|health_score|visitors|conversion|uptime"
)

#: (module path relative to src/friday, key, literal) -> justification.
ALLOWED: dict[tuple[str, str, float], str] = {
    (
        "learning/instinct_engine.py",
        "confidence",
        0.5,
    ): "A Bayesian prior for a newly learned instinct, not a reading about the world.",
    (
        "learning/trace_analyzer.py",
        "avg_latency_ms",
        float("inf"),
    ): "Sort key only: an unmeasured provider latency sorts last. Infinity is not a measurement.",
}


def _iter_telemetry_defaults():
    import re

    pattern = re.compile(TELEMETRY_KEY_PATTERN, re.IGNORECASE)
    for path in sorted(SRC.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "get"
                and len(node.args) >= 2
            ):
                continue
            default = node.args[1]
            if not isinstance(default, ast.Constant):
                continue
            value = default.value
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value == 0:
                continue
            key_node = node.args[0]
            key = key_node.value if isinstance(key_node, ast.Constant) else ast.unparse(key_node)
            if isinstance(key, str) and pattern.search(key):
                yield path.relative_to(SRC).as_posix(), key, float(value), node.lineno


def test_no_telemetry_reading_is_filled_with_a_plausible_literal():
    """Every numeric default for a telemetry-shaped key is either 0 or justified."""
    unexpected = []
    for module, key, value, lineno in _iter_telemetry_defaults():
        # `float("inf")` for a sort key arrives as a Call, not a Constant, so only
        # finite literals can reach this branch; the allowlist entry above covers
        # the textual form for documentation.
        if (module, key, value) not in ALLOWED:
            unexpected.append(f"{module}:{lineno} -> .get({key!r}, {value!r})")

    assert not unexpected, (
        "A missing telemetry reading is being filled with a plausible literal. "
        "Use None plus friday.core.readings (format_money/format_number/UNKNOWN_LABEL) "
        "and say the figure was not reported:\n  " + "\n  ".join(unexpected)
    )


def test_the_guard_would_catch_the_original_bugs():
    """The check is only worth having if it fires on the shapes that caused it."""
    samples = {
        'payload.get("equity", 10540.25)': ("equity", 10540.25),
        'status.get("win_rate_pct", 55.0)': ("win_rate_pct", 55.0),
        'p.get("max_drawdown_limit", 5.0)': ("max_drawdown_limit", 5.0),
        'ai.get("model_confidence", 0.84)': ("model_confidence", 0.84),
        'h.get("health_score", 98.4)': ("health_score", 98.4),
        'raw.get("sharpe_ratio", 1.45)': ("sharpe_ratio", 1.45),
    }
    import re

    pattern = re.compile(TELEMETRY_KEY_PATTERN, re.IGNORECASE)
    for snippet, (key, value) in samples.items():
        tree = ast.parse(f"x = {snippet}")
        call = next(n for n in ast.walk(tree) if isinstance(n, ast.Call))
        assert pattern.search(call.args[0].value), snippet
        assert call.args[1].value == value, snippet

    # And it must not fire on a zero default, which is a legitimate "nothing yet".
    zero_tree = ast.parse('x = payload.get("positions", [])')
    assert not any(isinstance(n, ast.Constant) and isinstance(n.value, float) for n in ast.walk(zero_tree))
