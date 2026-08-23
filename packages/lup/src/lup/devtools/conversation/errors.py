"""Shared failures for authenticated conversation retention."""


class ConversationDownloadError(RuntimeError):
    """A provider conversation could not be retained completely."""


class ConversationBrowserError(ConversationDownloadError):
    """A persistent conversation browser could not be opened."""
