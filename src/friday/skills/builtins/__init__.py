# -*- coding: utf-8 -*-
"""FRIDAY Built-in Skills Package."""

from friday.skills.builtins.network_diagnostic import NetworkDiagnosticSkill
from friday.skills.builtins.system_health_audit import SystemHealthAuditSkill
from friday.skills.builtins.file_search_and_read import FileSearchAndReadSkill

__all__ = [
    "NetworkDiagnosticSkill",
    "SystemHealthAuditSkill",
    "FileSearchAndReadSkill",
]

