"""Custom exceptions for smart_subtitle."""


class SmartSubtitleError(Exception):
    """Base exception for all smart_subtitle errors."""


class ConfigurationError(SmartSubtitleError):
    """Invalid configuration."""


class InputValidationError(SmartSubtitleError):
    """Invalid input data."""


class AudioExtractionError(SmartSubtitleError):
    """Failed to extract audio from video."""


class TranscriptionError(SmartSubtitleError):
    """Whisper transcription failed."""


class TranslationError(SmartSubtitleError):
    """LLM translation failed."""


class AlignmentError(SmartSubtitleError):
    """Alignment algorithm failed."""


class LLMError(SmartSubtitleError):
    """LLM API call failed."""


class CacheError(SmartSubtitleError):
    """Cache operation failed (non-critical)."""
