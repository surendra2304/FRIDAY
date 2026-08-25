# -*- coding: utf-8 -*-
"""FRIDAY Lab Experimentation Framework for Phase 18.

Runs multi-provider A/B benchmarking across defined tasks, records performance metrics
(latency, accuracy, success rate, failure modes) into SQLite, and provides CLI comparison reporting.
"""

import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from friday.core.logging import get_logger
from friday.core.types import Message, Role
from friday.llm.base import BaseLLMProvider
from friday.memory.sqlite import SQLiteConversationMemory

logger = get_logger("lab.experiment")


@dataclass
class ExperimentTask:
    """Task prompt and validation criteria for provider benchmarking."""

    task_id: str
    task_type: str  # e.g., 'coding', 'reasoning', 'system_control', 'summarization'
    prompt: str
    expected_keywords: List[str] = field(default_factory=list)
    verifier_prompt: Optional[str] = None


@dataclass
class TrialResult:
    """Result metrics for a single provider execution trial."""

    provider_name: str
    model_name: str
    task_id: str
    task_type: str
    prompt: str
    response_content: str
    latency_ms: float
    accuracy: float
    success: bool
    token_usage: int
    failure_mode: Optional[str] = None


class ExperimentRunner:
    """Executes parallel multi-provider benchmarks and stores metrics."""

    def __init__(
        self,
        providers: List[BaseLLMProvider],
        memory: Optional[SQLiteConversationMemory] = None,
        verifier_llm: Optional[BaseLLMProvider] = None,
    ) -> None:
        self.providers = providers
        self.memory = memory
        self.verifier_llm = verifier_llm

    def run_trial(self, provider: BaseLLMProvider, task: ExperimentTask) -> TrialResult:
        """Run single task against a single provider measuring exact latency and accuracy."""
        start_t = time.perf_counter()
        failure_mode = None
        success = False
        response_text = ""
        accuracy = 0.0
        token_usage = 0

        try:
            msg = provider.generate([Message(role=Role.USER, content=task.prompt)])
            response_text = msg.content.strip()
            success = bool(response_text)

            # Accuracy evaluation
            if task.expected_keywords:
                matches = sum(1 for kw in task.expected_keywords if kw.lower() in response_text.lower())
                accuracy = matches / len(task.expected_keywords)
                success = accuracy > 0.0
            else:
                success = bool(response_text)
                accuracy = 1.0 if success else 0.0

            # Optional verifier LLM scoring
            if self.verifier_llm and success:
                try:
                    v_prompt = (
                        f"Task: {task.prompt}\n"
                        f"Response: {response_text}\n"
                        "Evaluate correctness from 0.0 to 1.0. Output only a float score."
                    )
                    v_res = self.verifier_llm.generate([Message(role=Role.USER, content=v_prompt)])
                    score_str = v_res.content.strip().split()[0]
                    accuracy = float(score_str)
                except Exception:
                    pass

            token_usage = len(task.prompt.split()) + len(response_text.split())

        except Exception as e:
            failure_mode = str(e)
            success = False
            accuracy = 0.0

        latency_ms = (time.perf_counter() - start_t) * 1000.0

        result = TrialResult(
            provider_name=provider.provider_name,
            model_name=getattr(provider, "model", "default"),
            task_id=task.task_id,
            task_type=task.task_type,
            prompt=task.prompt,
            response_content=response_text,
            latency_ms=round(latency_ms, 2),
            accuracy=round(accuracy, 2),
            success=success,
            token_usage=token_usage,
            failure_mode=failure_mode,
        )

        if self.memory is not None and hasattr(self.memory, "record_experiment"):
            self.memory.record_experiment(
                experiment_name="A/B_benchmark",
                task_prompt=task.prompt,
                task_type=task.task_type,
                provider_name=result.provider_name,
                model_name=result.model_name,
                accuracy=result.accuracy,
                success=result.success,
                latency_ms=result.latency_ms,
                token_usage=result.token_usage,
                failure_mode=result.failure_mode,
                response_content=result.response_content,
            )

        return result

    def run_benchmark(self, tasks: List[ExperimentTask]) -> List[TrialResult]:
        """Run all tasks simultaneously across all registered providers."""
        results: List[TrialResult] = []
        with ThreadPoolExecutor(max_workers=max(4, len(self.providers) * len(tasks))) as executor:
            futures = []
            for task in tasks:
                for prov in self.providers:
                    futures.append(executor.submit(self.run_trial, prov, task))

            for fut in as_completed(futures):
                results.append(fut.result())

        return results


def run_standard_lab_suite(memory: Optional[SQLiteConversationMemory] = None) -> List[TrialResult]:
    """Predefined standard test suite across system intelligence tasks."""
    from friday.llm.factory import create_llm_provider
    from friday.core.config import get_settings

    settings = get_settings()
    providers: List[BaseLLMProvider] = []

    # Initialize all active cloud providers for comparison
    for prov_name, model_key in [
        ("groq", settings.groq_model),
        ("mistral", settings.mistral_model),
        ("openrouter", settings.openrouter_model),
    ]:
        try:
            prov = create_llm_provider(prov_name)
            providers.append(prov)
        except Exception as e:
            logger.debug(f"Provider {prov_name} omitted from Lab suite: {e}")

    if not providers:
        from friday.llm.mock_provider import MockLLMProvider
        providers = [MockLLMProvider(model="mock-fast"), MockLLMProvider(model="mock-deep")]

    suite_tasks = [
        ExperimentTask(
            task_id="t1_calc",
            task_type="reasoning",
            prompt="What is 45 multiplied by 12? Explain the intermediate steps.",
            expected_keywords=["540"],
        ),
        ExperimentTask(
            task_id="t2_code",
            task_type="coding",
            prompt="Write a Python function to reverse a string in-place or using slicing.",
            expected_keywords=["def", "return"],
        ),
        ExperimentTask(
            task_id="t3_sys",
            task_type="system_control",
            prompt="How do you check current RAM usage on Windows using PowerShell?",
            expected_keywords=["Get-Process", "Get-CimInstance", "TotalVisibleMemorySize", "FreePhysicalMemory", "powershell"],
        ),
    ]

    runner = ExperimentRunner(providers=providers, memory=memory)
    return runner.run_benchmark(suite_tasks)
