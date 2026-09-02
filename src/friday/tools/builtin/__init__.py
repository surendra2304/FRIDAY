"""Built-in tools for FRIDAY."""

from friday.tools.ai_universe_client import AIUniverseTool, GetAIUniverseStatusTool
from friday.tools.builtin.action_proposal import ProposeComputerActionTool
from friday.tools.builtin.android_control import (
    OpenAndroidAppTool,
    SwipeScreenTool,
    TapScreenTool,
    TypeTextTool as AndroidTypeTextTool,
)
from friday.tools.builtin.calculator import CalculatorTool
from friday.tools.builtin.calendar import GetTodaysEventsTool
from friday.tools.builtin.close_application import CloseApplicationTool
from friday.tools.builtin.dev_tools import (
    CreateGitBranchTool,
    ReadOwnCodebaseTool,
    ReplaceFileContentTool,
    RunTestsTool,
    WriteCodeFileTool,
)
from friday.tools.builtin.email_tools import SendEmailTool
from friday.tools.builtin.execute_computer_action import ExecuteComputerActionTool
from friday.tools.builtin.file_and_command import ExecuteCommandTool, FileOperationsTool
from friday.tools.builtin.file_listing import FileListingTool
from friday.tools.builtin.file_reader import FileReaderTool
from friday.tools.builtin.git_tools import GitCommitTool, GitPushTool, GitStatusTool
from friday.tools.builtin.github_tools import (
    CreateGitHubIssueTool,
    ListGitHubIssuesTool,
)
from friday.tools.builtin.health_monitor import HealthCheckTool
from friday.tools.builtin.launch_application import LaunchApplicationTool
from friday.tools.builtin.memory_search import MemorySearchTool
from friday.tools.builtin.open_application import OpenApplicationTool
from friday.tools.builtin.os_control import (
    ManageVolumeTool,
    ManageWindowsTool,
    SystemPowerControlTool,
)
from friday.tools.builtin.os_settings import (
    ToggleBluetoothTool,
    ToggleDarkModeTool,
    ToggleWifiTool,
)
from friday.tools.builtin.screen_ocr import (
    FindOnScreenTool,
    GetActiveAppContextTool,
    ReadActiveWindowTextTool,
    ReadScreenTextTool,
)
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool
from friday.tools.builtin.smart_home import ControlLightTool, ControlPlugTool
from friday.tools.builtin.system_control import SystemControlTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.builtin.system_monitor import GetSystemResourcesTool, KillProcessTool
from friday.tools.builtin.time_date import TimeDateTool
from friday.tools.builtin.type_text import TypeTextTool
from friday.tools.builtin.web_research import (
    FetchWebpageContentTool,
    SynthesizeInformationTool,
)
from friday.tools.builtin.web_tools import FetchWebpageTool, WebSearchTool
from friday.vision.screen_prediction import ScreenPredictionTool

__all__ = [
    "AIUniverseTool",
    "AndroidTypeTextTool",
    "OpenAndroidAppTool",
    "SwipeScreenTool",
    "TapScreenTool",
    "CalculatorTool",
    "CloseApplicationTool",
    "ControlLightTool",
    "ControlPlugTool",
    "CreateGitBranchTool",
    "CreateGitHubIssueTool",
    "ExecuteCommandTool",
    "ExecuteComputerActionTool",
    "FetchWebpageContentTool",
    "FetchWebpageTool",
    "FileListingTool",
    "FileOperationsTool",
    "FileReaderTool",
    "FindOnScreenTool",
    "GetAIUniverseStatusTool",
    "GetActiveAppContextTool",
    "GetSystemResourcesTool",
    "GetTodaysEventsTool",
    "GitCommitTool",
    "GitPushTool",
    "GitStatusTool",
    "HealthCheckTool",
    "KillProcessTool",
    "LaunchApplicationTool",
    "ListGitHubIssuesTool",
    "ManageVolumeTool",
    "ManageWindowsTool",
    "MemorySearchTool",
    "OpenApplicationTool",
    "ProposeComputerActionTool",
    "ReadActiveWindowTextTool",
    "ReadOwnCodebaseTool",
    "ReadScreenTextTool",
    "ReplaceFileContentTool",
    "RunTestsTool",
    "ScreenPredictionTool",
    "ScreenSnapshotTool",
    "SendEmailTool",
    "SynthesizeInformationTool",
    "SystemControlTool",
    "SystemInfoTool",
    "SystemPowerControlTool",
    "TimeDateTool",
    "ToggleBluetoothTool",
    "ToggleDarkModeTool",
    "ToggleWifiTool",
    "TypeTextTool",
    "WebSearchTool",
    "WriteCodeFileTool",
]
