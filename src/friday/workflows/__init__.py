"""Workflows package export."""

from friday.workflows.briefing_workflow import MorningBriefingWorkflow
from friday.workflows.dev_workflow import AutonomousDevWorkflow
from friday.workflows.email_workflow import EmailDraftingWorkflow
from friday.workflows.scheduler import ScheduledJob, WorkflowScheduler
from friday.workflows.self_improve_workflow import SelfImprovementWorkflow

__all__ = [
    "AutonomousDevWorkflow",
    "EmailDraftingWorkflow",
    "MorningBriefingWorkflow",
    "ScheduledJob",
    "SelfImprovementWorkflow",
    "WorkflowScheduler",
]

