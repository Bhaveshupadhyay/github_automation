from enum import Enum

DEFAULT_GEMINI_MODEL = "gemini-3.1-flash-lite"

class SpecialTags(str, Enum):
    """Domain Enum representing special control and summary tags used by the AI engine."""
    CLARIFICATION_NEEDED = "CLARIFICATION_NEEDED:"
    AGY_EXECUTION_SUMMARY = "AGY_EXECUTION_SUMMARY:"
