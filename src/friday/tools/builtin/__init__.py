"""Built-in tools for FRIDAY."""

from friday.tools.builtin.calculator import CalculatorTool
from friday.tools.builtin.file_reader import FileReaderTool
from friday.tools.builtin.file_listing import FileListingTool
from friday.tools.builtin.system_info import SystemInfoTool
from friday.tools.builtin.time_date import TimeDateTool
from friday.tools.builtin.memory_search import MemorySearchTool
from friday.tools.builtin.screen_snapshot import ScreenSnapshotTool
from friday.tools.builtin.action_proposal import ProposeComputerActionTool
from friday.tools.builtin.execute_computer_action import ExecuteComputerActionTool
from friday.tools.builtin.open_application import OpenApplicationTool
from friday.tools.builtin.type_text import TypeTextTool
from friday.tools.builtin.close_application import CloseApplicationTool
from friday.tools.builtin.os_control import ManageVolumeTool, SystemPowerControlTool, ManageWindowsTool
from friday.tools.builtin.web_tools import WebSearchTool, FetchWebpageTool
from friday.tools.builtin.file_and_command import FileOperationsTool, ExecuteCommandTool
from friday.tools.builtin.screen_ocr import (
    ReadScreenTextTool,
    FindOnScreenTool,
    GetActiveAppContextTool,
    ReadActiveWindowTextTool,
)
from friday.tools.builtin.git_tools import GitStatusTool, GitCommitTool, GitPushTool
from friday.tools.builtin.github_tools import ListGitHubIssuesTool, CreateGitHubIssueTool
from friday.tools.builtin.system_monitor import GetSystemResourcesTool, KillProcessTool
from friday.tools.builtin.launch_application import LaunchApplicationTool
from friday.tools.builtin.system_control import SystemControlTool
from friday.tools.builtin.health_monitor import HealthCheckTool
from friday.tools.builtin.dev_tools import (
    WriteCodeFileTool,
    RunTestsTool,
    CreateGitBranchTool,
    ReadOwnCodebaseTool,
)
from friday.tools.builtin.smart_home import ControlLightTool, ControlPlugTool
from friday.tools.builtin.web_research import FetchWebpageContentTool, SynthesizeInformationTool
from friday.tools.builtin.os_settings import ToggleDarkModeTool, ToggleBluetoothTool, ToggleWifiTool
from friday.tools.builtin.calendar import GetTodaysEventsTool
from friday.tools.builtin.email_tools import SendEmailTool
from friday.vision.screen_prediction import ScreenPredictionTool

__all__ = [
    "CalculatorTool",
    "FileReaderTool",
    "FileListingTool",
    "SystemInfoTool",
    "TimeDateTool",
    "MemorySearchTool",
    "ScreenSnapshotTool",
    "ProposeComputerActionTool",
    "ExecuteComputerActionTool",
    "OpenApplicationTool",
    "TypeTextTool",
    "CloseApplicationTool",
    "ManageVolumeTool",
    "SystemPowerControlTool",
    "ManageWindowsTool",
    "WebSearchTool",
    "FetchWebpageTool",
    "FileOperationsTool",
    "ExecuteCommandTool",
    "ReadScreenTextTool",
    "FindOnScreenTool",
    "GetActiveAppContextTool",
    "ReadActiveWindowTextTool",
    "GitStatusTool",
    "GitCommitTool",
    "GitPushTool",
    "ListGitHubIssuesTool",
    "CreateGitHubIssueTool",
    "GetSystemResourcesTool",
    "KillProcessTool",
    "LaunchApplicationTool",
    "SystemControlTool",
    "HealthCheckTool",
    "WriteCodeFileTool",
    "RunTestsTool",
    "CreateGitBranchTool",
    "ReadOwnCodebaseTool",
    "ControlLightTool",
    "ControlPlugTool",
    "FetchWebpageContentTool",
    "SynthesizeInformationTool",
    "ToggleDarkModeTool",
    "ToggleBluetoothTool",
    "ToggleWifiTool",
    "GetTodaysEventsTool",
    "SendEmailTool",
    "ScreenPredictionTool",
]
