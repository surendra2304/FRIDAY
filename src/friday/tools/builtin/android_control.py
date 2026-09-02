import subprocess
from typing import Any, Type

from pydantic import BaseModel, Field

from friday.tools.base import BaseTool


class ADBBaseTool(BaseTool):
    """Base class for ADB tools checking connectivity."""

    def _run_adb(self, args: list[str]) -> str:
        cmd = ["adb"] + args
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"ADB command failed: {e.stderr.strip() or e.stdout.strip()}")
        except FileNotFoundError:
            raise RuntimeError("ADB not found in PATH. Please install Android Platform Tools.")


class TapScreenArgs(BaseModel):
    x: int = Field(..., description="X coordinate on screen")
    y: int = Field(..., description="Y coordinate on screen")


class TapScreenTool(ADBBaseTool):
    name: str = "android_tap"
    description: str = "Taps the Android device screen at the specified (x, y) coordinates."
    args_schema: Type[BaseModel] = TapScreenArgs

    def execute(self, args: TapScreenArgs, context: dict[str, Any]) -> str:
        self._run_adb(["shell", "input", "tap", str(args.x), str(args.y)])
        return f"Tapped screen at ({args.x}, {args.y})."


class SwipeScreenArgs(BaseModel):
    x1: int = Field(..., description="Start X coordinate")
    y1: int = Field(..., description="Start Y coordinate")
    x2: int = Field(..., description="End X coordinate")
    y2: int = Field(..., description="End Y coordinate")
    duration: int = Field(500, description="Duration in milliseconds")


class SwipeScreenTool(ADBBaseTool):
    name: str = "android_swipe"
    description: str = "Swipes the Android device screen from (x1, y1) to (x2, y2)."
    args_schema: Type[BaseModel] = SwipeScreenArgs

    def execute(self, args: SwipeScreenArgs, context: dict[str, Any]) -> str:
        self._run_adb(
            ["shell", "input", "swipe", str(args.x1), str(args.y1), str(args.x2), str(args.y2), str(args.duration)]
        )
        return f"Swiped screen from ({args.x1}, {args.y1}) to ({args.x2}, {args.y2})."


class OpenAndroidAppArgs(BaseModel):
    package_name: str = Field(..., description="The Android package name (e.g. 'com.google.android.youtube')")


class OpenAndroidAppTool(ADBBaseTool):
    name: str = "android_open_app"
    description: str = "Opens a specific application on the connected Android device via monkey."
    args_schema: Type[BaseModel] = OpenAndroidAppArgs

    def execute(self, args: OpenAndroidAppArgs, context: dict[str, Any]) -> str:
        self._run_adb(["shell", "monkey", "-p", args.package_name, "-c", "android.intent.category.LAUNCHER", "1"])
        return f"Launched app {args.package_name}."


class TypeTextArgs(BaseModel):
    text: str = Field(..., description="The text to type on the Android device")


class TypeTextTool(ADBBaseTool):
    name: str = "android_type_text"
    description: str = "Types text on the Android device (requires a text field to be focused)."
    args_schema: Type[BaseModel] = TypeTextArgs

    def execute(self, args: TypeTextArgs, context: dict[str, Any]) -> str:
        escaped_text = args.text.replace(" ", "%s")  # ADB requires %s for spaces
        self._run_adb(["shell", "input", "text", escaped_text])
        return f"Typed text: {args.text}"
