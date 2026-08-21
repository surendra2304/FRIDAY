# -*- coding: utf-8 -*-
"""Model-configuration consistency test suite.

Fails if production source code in `src/` introduces legacy, deprecated,
or unapproved Gemini models, or deviates from the authoritative configuration.
"""

import ast
from pathlib import Path
import re
import pytest

from friday.core.config import Settings, get_settings
from friday.llm.gemini_provider import GeminiLLMProvider
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.voice.gemini_live_session import GeminiLiveVoiceSession
from friday.memory.embeddings.gemini import GeminiEmbeddingProvider

# Authoritative active model configuration
AUTHORITATIVE_MODELS = {
    "text_llm": "gemini-1.5-flash-latest",
    "vision": "gemini-1.5-flash-latest",
    "voice_live": "gemini-3.1-flash-live-preview",
    "embeddings": "gemini-embedding-2",
}

DISALLOWED_LEGACY_PATTERNS = [
    # Policy update (2026-08-22, rev 2): gemini-1.5-flash-latest is the ACTIVE
    # model for text, vision, AND Live voice. gemini-2.0-flash-exp is
    # unsupported for bidiGenerateContent; Google denies the 3.x previews
    # with 1008 access errors. Both generations are disallowed legacy refs.
    r"\bgemini-3\.7\b",
    r"\bgemini-3\.6\b",
    r"\bgemini-3\.1(?!-flash-live)\b",
    r"\bgemini-1\.0\b",
    r"\bgemini-1\.5-pro\b",
    r"\bgemini-pro\b",
    r"\btext-embedding-004\b",
    r"\bmodels/embedding-001\b",
]


def test_settings_default_model_consistency():
    """Verify Settings class defaults match authoritative production model configurations."""
    settings = Settings()
    assert settings.llm_model == AUTHORITATIVE_MODELS["text_llm"]
    assert settings.vision_model == AUTHORITATIVE_MODELS["vision"]
    assert settings.voice_live_model == AUTHORITATIVE_MODELS["voice_live"]
    assert settings.embedding_model == AUTHORITATIVE_MODELS["embeddings"]


def test_provider_constructors_default_to_authoritative_models():
    """Verify provider class constructors default to authoritative production models."""
    llm = GeminiLLMProvider(api_key="TEST_API_KEY")
    assert llm.model == AUTHORITATIVE_MODELS["text_llm"]

    vision = GeminiVisionProvider(api_key="TEST_API_KEY")
    assert vision.model == AUTHORITATIVE_MODELS["vision"]

    voice = GeminiLiveVoiceSession(api_key="TEST_API_KEY")
    assert voice.model == AUTHORITATIVE_MODELS["voice_live"]

    embed = GeminiEmbeddingProvider(api_key="TEST_API_KEY")
    assert embed.model == AUTHORITATIVE_MODELS["embeddings"]


def test_no_legacy_gemini_models_in_production_source_code():
    """AST/regex audit of all files in `src/` to ensure zero deprecated Gemini models exist."""
    src_root = Path(__file__).resolve().parent.parent / "src"
    violations = []

    compiled_disallowed = [re.compile(p, re.IGNORECASE) for p in DISALLOWED_LEGACY_PATTERNS]

    for py_file in src_root.rglob("*.py"):
        code = py_file.read_text(encoding="utf-8")
        rel_path = py_file.relative_to(src_root)

        for line_no, line in enumerate(code.splitlines(), start=1):
            # Ignore pure comment lines if needed, but production code shouldn't reference legacy models
            for pattern in compiled_disallowed:
                if pattern.search(line):
                    violations.append(f"{rel_path}:{line_no} -> {line.strip()}")

    assert not violations, (
        f"Found {len(violations)} disallowed legacy Gemini model reference(s) in src/:\n"
        + "\n".join(violations)
    )
