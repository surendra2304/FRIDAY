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
from friday.operators.guardian_angel import GuardianAngelOperator
from friday.operators.forge_monitor import ForgeMonitorOperator
from friday.operators.forge_supervisor_operator import ForgeSupervisorOperator
from friday.operators.forge_health_operator import ForgeHealthOperator
from friday.operators.nexus_vigilance_operator import NexusVigilanceOperator
from friday.operators.ecosystem_anomaly_operator import EcosystemAnomalyDetection
from friday.operators.memory_health_operator import MemoryHealthMonitor
from friday.operators.scheduled_intelligence import ScheduledIntelligenceOperator
from friday.operators.anomaly_investigator import ProactiveAnomalyInvestigator
from friday.operators.cascade_detector import CascadeFailureDetector

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
    "GuardianAngelOperator",
    "ForgeMonitorOperator",
    "ForgeSupervisorOperator",
    "ForgeHealthOperator",
    "NexusVigilanceOperator",
    "EcosystemAnomalyDetection",
    "MemoryHealthMonitor",
    "ScheduledIntelligenceOperator",
    "ProactiveAnomalyInvestigator",
    "CascadeFailureDetector",
]
