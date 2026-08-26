class ReadingAssistantError(Exception):
    """Base application error that can safely be shown in the UI."""


class CaptureError(ReadingAssistantError):
    pass


class ProtectedCaptureError(CaptureError):
    pass


class DuplicatePageError(CaptureError):
    pass


class PageChangeTimeout(CaptureError):
    pass


class LLMConnectionError(ReadingAssistantError):
    pass


class LLMResponseError(ReadingAssistantError):
    pass


class UnsafeEndpointError(ReadingAssistantError):
    pass


class ExcessiveTranscriptionError(LLMResponseError):
    pass

