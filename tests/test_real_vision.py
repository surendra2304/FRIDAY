"""Real hardware manual verification test for Gemini Multimodal Vision.

Test Type: HARDWARE / LIVE

Sends synthetic test image bytes to the official Google Gemini multimodal API using GeminiVisionProvider.
"""

import pytest

# Mark as hardware test (opt-in only via pytest -m hardware)
pytestmark = [pytest.mark.hardware, pytest.mark.live]

from friday.auth.credential_pool import credential_pool
from friday.core.config import get_settings
from friday.vision.gemini_vision import GeminiVisionProvider
from friday.vision.mock_screen import create_synthetic_png


def test_hardware_gemini_vision_analysis():
    """Live Gemini multimodal visual analysis test."""
    settings = get_settings()
    api_key = credential_pool.get_active_key() or settings.gemini_api_key or settings.llm_api_key
    if not api_key:
        pytest.skip("No real Gemini API key configured in environment. Skipping live vision test.")

    provider = GeminiVisionProvider(credential_pool=credential_pool, model=settings.vision_model)
    image_bytes = create_synthetic_png(64, 64, (0, 180, 255))
    prompt = "Describe the colors and geometric shapes visible in this image concisely."

    result = provider.analyze_image(image_bytes, mime_type="image/png", prompt=prompt)
    assert result.is_error is False, f"Vision call failed: {result.text}"
    assert len(result.text) > 10, "Response must contain meaningful text description"
