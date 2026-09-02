import logging
import os
import random
import re
import subprocess
import time
import warnings
from collections.abc import Callable
from typing import Any
from urllib.parse import quote_plus
import uuid
from datetime import datetime
from friday.agent.checkpoint import TaskCheckpoint, TaskCheckpointStore
from friday.agent.cognitive import CognitiveIntelligenceEngine, CognitivePhase
from friday.agent.executor import (
    ExecutionProgress,
    TaskExecutionEngine,
    TaskExecutionResult,
)
from friday.agent.planner import GoalDecomposer, TaskPlan
from friday.agent.prompts import build_system_message
from friday.agent.state import ReasoningStateMachine, TaskState
from friday.agents.base_agent import AgentTask, BaseAgent
from friday.agents.decomposer import TaskDecomposer
from friday.agents.registry import AgentRegistry
from friday.agents.router import AgentRouter
from friday.core.auth import BaseAuthorizer, DefaultSecureAuthorizer
from friday.core.config import Settings, get_settings
from friday.core.logging import get_logger
from friday.core.types import (
    AgentResponse,
    AuthorizationDecision,
    AuthorizationRequest,
    MemorySearchResult,
    Message,
    Role,
    SafetyLevel,
    ToolCall,
    ToolResult,
    TrustLevel,
)
from friday.llm.base import BaseLLMProvider
from friday.llm.factory import create_llm_provider
from friday.memory.base import BaseMemory
from friday.memory.factory import create_memory
from friday.memory.policies import should_retrieve_memory
from friday.memory.task_context import ActiveTaskContext
from friday.observability.notifications import NotificationManager
from friday.routing.capability_router import CapabilityRouter
from friday.tools.builtin import (
    AIUniverseTool,
    CalculatorTool,
    CloseApplicationTool,
    ControlLightTool,
    ControlPlugTool,
    CreateGitBranchTool,
    CreateGitHubIssueTool,
    ExecuteCommandTool,
    FetchWebpageContentTool,
    FetchWebpageTool,
    FileListingTool,
    FileOperationsTool,
    FileReaderTool,
    FindOnScreenTool,
    GetActiveAppContextTool,
    GetAIUniverseStatusTool,
    GetSystemResourcesTool,
    GetTodaysEventsTool,
    GitCommitTool,
    GitPushTool,
    GitStatusTool,
    HealthCheckTool,
    KillProcessTool,
    LaunchApplicationTool,
    ListGitHubIssuesTool,
    ManageVolumeTool,
    ManageWindowsTool,
    MemorySearchTool,
    OpenApplicationTool,
    ProposeComputerActionTool,
    ReadActiveWindowTextTool,
    ReadOwnCodebaseTool,
    ReadScreenTextTool,
    ReplaceFileContentTool,
    RunTestsTool,
    ScreenPredictionTool,
    ScreenSnapshotTool,
    SendEmailTool,
    SynthesizeInformationTool,
    SystemControlTool,
    SystemInfoTool,
    SystemPowerControlTool,
    TimeDateTool,
    ToggleBluetoothTool,
    ToggleDarkModeTool,
    ToggleWifiTool,
    TypeTextTool,
    WebSearchTool,
    WriteCodeFileTool,
)
from friday.tools.registry import ToolRegistry
from friday.vision.actions import ActionType
from friday.vision.computer_control import ComputerActionExecutor
from friday.vision.detector import DeterministicActionDetector
from friday.vision.intent_detector import ActionIntent, IntentDetector
from friday.vision.windows_input_driver import (
    WindowsNativeInputDriver,
    check_desktop_interactivity,
)

"""Memory management capabilities for the FridayAgent."""

import asyncio
import json
from typing import Dict, List, Optional
from pathlib import Path


logger = logging.getLogger(__name__)


class MemoryMixin:
    def switch_conversation(self, conversation_id: str) -> None:
            """Switch the active conversation session."""
            self.memory.load_conversation(conversation_id)

    def create_new_conversation(self, title: str | None = None) -> str | None:
            """Create and activate a new conversation session."""
            return self.memory.create_conversation(title=title)

    def list_conversations(self, limit: int = 50) -> list[dict[str, Any]]:
            """List available conversation sessions."""
            return self.memory.list_conversations(limit=limit)

    def get_current_conversation(self) -> dict[str, Any] | None:
            """Retrieve metadata for the current active conversation."""
            if self.conversation_id:
                return self.memory.get_conversation(self.conversation_id)
            return None

    def rename_conversation(self, new_title: str, conversation_id: str | None = None) -> bool:
            """Rename an existing conversation."""
            target_id = conversation_id or self.conversation_id
            if target_id:
                return self.memory.rename_conversation(target_id, new_title)
            return False

    def delete_conversation(self, conversation_id: str, confirm: bool = True) -> bool:
            """Delete a conversation session and all its messages."""
            return self.memory.delete_conversation(conversation_id, confirm=confirm)

    def purge_all_memory(self, confirm: bool = True) -> int:
            """Permanently delete all stored conversations and messages."""
            return self.memory.purge_all(confirm=confirm)

    def clear_all_conversations(self, confirm: bool = True) -> int:
            """Permanently delete all stored conversations and messages."""
            return self.purge_all_memory(confirm=confirm)

    def clear_memory(self, confirm: bool = True) -> None:
            """Clear messages from the active conversation."""
            self.memory.clear(conversation_id=self.conversation_id, confirm=confirm)

    def prune_memory(self, retention_days: int | None = None) -> int:
            """Prune messages older than the retention threshold."""
            days = retention_days or self.settings.memory_retention_days
            if days:
                return self.memory.prune_expired_messages(days)
            return 0

    def backup_database(self, backup_path: str) -> str:
            """Create an online hot backup of the persistent database to the target destination path."""
            return self.memory.backup(backup_path)

    def export_conversation(self, conversation_id: str | None = None) -> dict[str, Any]:
            """Export full conversation metadata and messages to a dictionary."""
            target_id = conversation_id or self.conversation_id
            if not target_id:
                raise ValueError("No active conversation to export.")
            return self.memory.export_conversation_to_dict(target_id)

    def search_memory(
            self,
            query: str,
            conversation_id: str | None = None,
            limit: int = 10,
            start_time: datetime | None = None,
            end_time: datetime | None = None,
        ) -> list[MemorySearchResult]:
            """Search historical conversation messages."""
            return self.memory.search(
                query=query,
                conversation_id=conversation_id,
                limit=limit,
                start_time=start_time,
                end_time=end_time,
            )

    def _retrieve_relevant_memories(self, query: str) -> list[MemorySearchResult]:
            """Controlled retrieval of relevant historical context based on settings."""
            if not getattr(self.settings, "enable_auto_recall", True):
                return []

            mode = getattr(self.settings, "retrieval_mode", "hybrid").lower().strip()
            if mode in ("none", "disabled", "false", ""):
                return []

            clean_query = query.strip()
            if not should_retrieve_memory(clean_query):
                return []

            limit = getattr(self.settings, "max_recalled_memories", 3)
            threshold = getattr(self.settings, "recall_similarity_threshold", 0.6)
            max_chars = getattr(self.settings, "max_recall_chars", 1000)

            results: list[MemorySearchResult] = []
            try:
                if mode == "semantic":
                    sem_res = self.memory.search_semantic(clean_query, limit=limit, threshold=threshold)
                    results = [
                        MemorySearchResult(
                            conversation_id=sr.conversation_id,
                            conversation_title=sr.metadata.get("conversation_title", ""),
                            message_id=sr.message_id or sr.record_id,
                            role=Role(sr.metadata.get("role", "assistant")),
                            content=sr.source_text,
                            timestamp=sr.created_at,
                            score=sr.score,
                        )
                        for sr in sem_res
                    ]
                elif mode == "fts":
                    results = self.memory.search(clean_query, limit=limit)
                else:  # hybrid
                    results = self.memory.search_hybrid(clean_query, limit=limit)
            except Exception as e:
                logger.warning(f"Auto memory recall failed: {e}")
                return []

            filtered: list[MemorySearchResult] = []
            total_chars = 0
            for r in results:
                if r.content.strip().lower() == clean_query.lower():
                    continue
                if total_chars + len(r.content) > max_chars:
                    break
                filtered.append(r)
                total_chars += len(r.content)

            return filtered

