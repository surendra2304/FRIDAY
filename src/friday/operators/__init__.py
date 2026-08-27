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
from friday.operators.advisory_watchdog import AdvisoryWatchdogOperator
from friday.operators.ab_test_operator import ABTestOperator
from friday.operators.testnet_advisory_operator import TestnetAdvisoryOperator
from friday.operators.live_vigilance_operator import LiveVigilanceOperator
from friday.operators.portfolio_supervisor import PortfolioSupervisorOperator
from friday.operators.evolution_oversight import EvolutionOversightOperator
from friday.operators.intelligence_vigilance import IntelligenceVigilanceOperator

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
    "AdvisoryWatchdogOperator",
    "ABTestOperator",
    "TestnetAdvisoryOperator",
    "LiveVigilanceOperator",
    "PortfolioSupervisorOperator",
    "EvolutionOversightOperator",
    "IntelligenceVigilanceOperator",
]
