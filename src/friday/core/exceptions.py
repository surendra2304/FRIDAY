"""Domain exception hierarchy for FRIDAY."""

class FridayError(Exception):
    """Base exception for all errors within FRIDAY."""
    pass


class ConfigError(FridayError):
    """Raised when configuration validation or loading fails."""
    pass


class LLMProviderError(FridayError):
    """Raised when an LLM provider request fails or returns an invalid payload."""
    pass


class ToolError(FridayError):
    """Raised when a tool fails to register, validate, or execute."""
    pass


class SafetyError(FridayError):
    """Raised when an operation violates safety constraints or confirmation is rejected."""
    pass


class MemoryError(FridayError):
    """Raised when memory operations fail."""
    pass
