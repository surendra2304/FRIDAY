# -*- coding: utf-8 -*-
"""FRIDAY Persistent Operators System (Inspired by OpenJarvis)."""

from friday.operators.base_operator import BaseOperator, OperatorExecutionResult, OperatorState
from friday.operators.triggers import (
    BaseTrigger,
    FileSystemTrigger,
    ProcessTrigger,
    ConditionTrigger,
    IntervalTrigger,
)
from friday.operators.manager import OperatorManager, operator_manager

__all__ = [
    "BaseOperator",
    "OperatorExecutionResult",
    "OperatorState",
    "BaseTrigger",
    "FileSystemTrigger",
    "ProcessTrigger",
    "ConditionTrigger",
    "IntervalTrigger",
    "OperatorManager",
    "operator_manager",
]
