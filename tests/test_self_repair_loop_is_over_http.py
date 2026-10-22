"""The E1 end-to-end driver must prove the loop over real HTTP.

The self-repair gate's value is that it is a separate authority: a caller cannot
apply a patch without a signed review it cannot forge. A driver that imports the
gate and calls its methods directly would print a convincing transcript while
proving nothing about the HTTP surface the other agents actually call.

So the property under test is structural, and it is asserted against the source
rather than by running the full loop: running the loop needs real git, real
pytest, and the sibling Forge and Sentinel checkouts, none of which exist in CI.
"""

from __future__ import annotations

import ast
from pathlib import Path

LOOP = Path(__file__).resolve().parents[1] / "research" / "self_repair_loop.py"


def _imported_modules() -> set[str]:
    tree = ast.parse(LOOP.read_text(encoding="utf-8"))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def test_driver_does_not_import_the_gate_it_is_proving():
    """Importing the gate would let the driver reach it without the HTTP surface."""
    modules = _imported_modules()
    assert "friday.autonomous.self_repair" not in modules, (
        "the driver imports the gate module, so it could call it directly instead "
        "of going through the API; that would not prove the deployed surface"
    )


def test_driver_still_uses_the_real_sibling_implementations():
    """The other two services must be the real code, not a stand-in."""
    modules = _imported_modules()
    assert "app.selfrepair.proposer" in modules, "Forge's real proposer is not imported"
    assert "sentinel.core.selfrepair.reviewer" in modules, (
        "Sentinel's real reviewer is not imported"
    )


def test_driver_starts_the_gate_as_a_separate_process():
    """In-process execution is what this whole change set replaced."""
    source = LOOP.read_text(encoding="utf-8")
    assert "uvicorn" in source, "no uvicorn server is started"
    assert "friday.api.server:app" in source, (
        "the driver must serve the real application object, not a stand-in app"
    )
    assert "subprocess.Popen" in source, "the server must be its own process"


def test_driver_refuses_to_claim_more_than_it_measures():
    """The driver must document its own limits rather than imply a live proof."""
    source = LOOP.read_text(encoding="utf-8").lower()
    assert "not a deployment secret" in source, (
        "the test key literals must be labelled as literals, not deployment secrets"
    )
    assert "run inside this driver process" in source, (
        "the driver must state that Forge and Sentinel do not cross the network "
        "boundary in this proof"
    )
    assert "nothing in the transcript is mocked" in source, (
        "the driver must state what in the transcript is real"
    )
