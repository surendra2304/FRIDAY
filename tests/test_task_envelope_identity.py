"""Identity and retry metadata invariants for the universal task envelope."""

import pytest
from pydantic import ValidationError

from friday.core.task_envelope import TaskEnvelope


def test_generated_idempotency_key_is_derived_from_generated_task_id() -> None:
    envelope = TaskEnvelope()

    assert envelope.idempotency_key == f"idem_{envelope.task_id}"
    assert len(envelope.idempotency_key or "") <= 128


def test_explicit_task_id_produces_a_stable_default_idempotency_key() -> None:
    envelope = TaskEnvelope(task_id="task-retry-42")

    assert envelope.idempotency_key == "idem_task-retry-42"
    replay = TaskEnvelope.model_validate(envelope.model_dump())
    assert replay.task_id == envelope.task_id
    assert replay.idempotency_key == envelope.idempotency_key


def test_explicit_idempotency_key_is_preserved() -> None:
    envelope = TaskEnvelope(task_id="task-42", idempotency_key="client-retry-token")

    assert envelope.idempotency_key == "client-retry-token"


def test_task_id_length_matches_persisted_cross_service_contract() -> None:
    with pytest.raises(ValidationError):
        TaskEnvelope(task_id="t" * 65)


def test_empty_task_id_is_rejected() -> None:
    with pytest.raises(ValidationError):
        TaskEnvelope(task_id="")
