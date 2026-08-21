# -*- coding: utf-8 -*-
"""DEPRECATED ALIAS: Redirects to test_simulation_multimodal_validation.py.

This file was renamed to test_simulation_multimodal_validation.py to accurately reflect
that it executes offline in-memory simulations rather than physical hardware.
"""

from tests.test_simulation_multimodal_validation import (
    test_simulation_voice_perception_autonomous_execution_flow as test_end_to_end_voice_perception_autonomous_execution_flow,
    test_simulation_interruption_and_resumption,
)

__all__ = [
    "test_end_to_end_voice_perception_autonomous_execution_flow",
    "test_simulation_interruption_and_resumption",
]
