"""FRIDAY Built-in Skills Package."""

from friday.skills.builtins.file_search_and_read import FileSearchAndReadSkill
from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill
from friday.skills.builtins.system_health_audit import SystemHealthAuditSkill

__all__ = [
    "FileSearchAndReadSkill",
    "NetworkDiagnosticSkill",
    "SystemHealthAuditSkill",
]

