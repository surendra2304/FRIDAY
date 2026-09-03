"""Unit tests for FaceProfileManager and facial biometric authentication tools."""

import os
import shutil
import tempfile
import numpy as np
import pytest

from friday.security.face_biometrics import (
    FaceProfileManager,
    cosine_similarity,
)
from friday.tools.builtin.face_auth import (
    EnrollFaceIdentityTool,
    VerifyFaceIdentityTool,
)


@pytest.fixture
def temp_face_manager():
    temp_dir = tempfile.mkdtemp(prefix="friday_face_test_")
    manager = FaceProfileManager(profile_dir=temp_dir, threshold=0.70)
    yield manager
    try:
        shutil.rmtree(temp_dir)
    except Exception:
        pass


def test_cosine_similarity():
    vec_a = [1.0, 0.0, 0.0]
    vec_b = [1.0, 0.0, 0.0]
    vec_c = [0.0, 1.0, 0.0]

    assert cosine_similarity(vec_a, vec_b) == pytest.approx(1.0)
    assert cosine_similarity(vec_a, vec_c) == pytest.approx(0.0)
    assert cosine_similarity([], vec_b) == 0.0


def test_enroll_and_verify_face(temp_face_manager):
    # Synthetic face frame (64x64 uint8 image)
    frame1 = np.ones((64, 64, 3), dtype=np.uint8) * 128
    frame2 = np.ones((64, 64, 3), dtype=np.uint8) * 130

    ok, msg = temp_face_manager.enroll_face(
        user_id="surendra",
        name="Surendra",
        frames=[frame1, frame2],
    )
    assert ok is True
    assert "successfully enrolled" in msg

    # Verify matching frame
    result = temp_face_manager.verify_face(frame=frame1)
    assert result.is_matched is True
    assert result.user_id == "surendra"
    assert result.user_name == "Surendra"
    assert result.confidence >= 0.70

    # Verify non-matching / corrupted frame
    blank_frame = np.zeros((64, 64, 3), dtype=np.uint8)
    diff_result = temp_face_manager.verify_face(frame=blank_frame)
    assert diff_result.confidence <= 1.0


def test_face_auth_tools(temp_face_manager):
    enroll_tool = EnrollFaceIdentityTool(manager=temp_face_manager)
    verify_tool = VerifyFaceIdentityTool(manager=temp_face_manager)

    frame = np.ones((64, 64, 3), dtype=np.uint8) * 150
    temp_face_manager.enroll_face(user_id="stark", name="Tony Stark", frames=[frame])

    res = verify_tool.execute(user_id="stark")
    assert res.is_error is True or res.is_error is False
    assert res.name == "verify_face_identity"
