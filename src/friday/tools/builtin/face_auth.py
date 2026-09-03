"""Tools for face biometric enrollment and verification in FRIDAY."""

from __future__ import annotations

from typing import Any

from friday.core.logging import get_logger
from friday.core.types import SafetyLevel, ToolResult
from friday.security.face_biometrics import FaceProfileManager
from friday.tools.base import BaseTool

logger = get_logger("tools.face_auth")


class VerifyFaceIdentityTool(BaseTool):
    """Verify the user currently sitting in front of the camera using face biometrics."""

    name = "verify_face_identity"
    description = (
        "Verify the user in front of the webcam against enrolled facial biometric profiles. "
        "Returns whether the user was authenticated, their name, and verification confidence score."
    )
    safety_level = SafetyLevel.SAFE
    parameters = {
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "Optional specific user ID to verify against. If omitted, checks all enrolled profiles.",
            },
            "camera_index": {
                "type": "integer",
                "description": "Camera device index (default: 0).",
            },
        },
        "required": [],
    }

    def __init__(self, manager: FaceProfileManager | None = None) -> None:
        super().__init__()
        self._manager = manager

    def _get_manager(self) -> FaceProfileManager:
        if self._manager is None:
            self._manager = FaceProfileManager()
        return self._manager

    def execute(self, user_id: str | None = None, camera_index: int = 0, **kwargs: Any) -> ToolResult:
        mgr = self._get_manager()
        res = mgr.verify_face(camera_index=camera_index, user_id=user_id)

        if res.is_matched:
            return ToolResult(
                name=self.name,
                content=(
                    f"Facial Identity Verified Successfully.\n"
                    f"User: {res.user_name} (ID: {res.user_id})\n"
                    f"Confidence: {res.confidence:.1%}\n"
                    f"Authentication State: Confirmed"
                ),
                is_error=False,
                safety_level=self.safety_level,
            )
        else:
            return ToolResult(
                name=self.name,
                content=f"Facial Identity Verification Failed: {res.error_message or 'No match found.'}",
                is_error=True,
                safety_level=self.safety_level,
            )


class EnrollFaceIdentityTool(BaseTool):
    """Enroll a new face profile using the webcam. Marked SENSITIVE for authorization."""

    name = "enroll_face_identity"
    description = (
        "Enroll a user's face into FRIDAY's biometric identity profile storage using the webcam. "
        "Requires authorization as a SENSITIVE biometric credential action."
    )
    safety_level = SafetyLevel.SENSITIVE
    parameters = {
        "type": "object",
        "properties": {
            "name": {
                "type": "string",
                "description": "User's full name (e.g. 'Surendra').",
            },
            "user_id": {
                "type": "string",
                "description": "Optional unique identifier for the user (default: slug of name).",
            },
            "camera_index": {
                "type": "integer",
                "description": "Camera device index (default: 0).",
            },
        },
        "required": ["name"],
    }

    def __init__(self, manager: FaceProfileManager | None = None) -> None:
        super().__init__()
        self._manager = manager

    def _get_manager(self) -> FaceProfileManager:
        if self._manager is None:
            self._manager = FaceProfileManager()
        return self._manager

    def execute(self, name: str, user_id: str | None = None, camera_index: int = 0, **kwargs: Any) -> ToolResult:
        uname = (name or "").strip()
        if not uname:
            return ToolResult(
                name=self.name,
                content="Error: User name is required for face profile enrollment.",
                is_error=True,
                safety_level=self.safety_level,
            )

        uid = (user_id or uname.lower().replace(" ", "_")).strip()
        mgr = self._get_manager()
        ok, msg = mgr.enroll_face(user_id=uid, name=uname, camera_index=camera_index)

        return ToolResult(
            name=self.name,
            content=msg,
            is_error=not ok,
            safety_level=self.safety_level,
        )
