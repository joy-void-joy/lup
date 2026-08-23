"""Retain complete ChatGPT conversations through an authenticated browser."""

import hashlib
import json
import logging
import mimetypes
import shutil
import tempfile
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import ParseResult, quote, urljoin, urlparse

from playwright.async_api import (
    APIRequestContext,
    APIResponse,
    Error as PlaywrightError,
)
from pydantic import AliasChoices, BaseModel, Field, TypeAdapter, model_validator

from lup.types import JsonValue
from lup.devtools.conversation.browser import browser_context
from lup.devtools.conversation.errors import ConversationDownloadError

logger = logging.getLogger(__name__)


class ChatGPTDownloadError(ConversationDownloadError):
    """A ChatGPT conversation could not be retained completely."""


class ChatGPTAuthenticationRequired(ChatGPTDownloadError):
    """An ordinary conversation needs a fresh ChatGPT browser login."""


class Payload(BaseModel, frozen=True, extra="ignore"):
    """A tolerant typed view over ChatGPT's unsupported web payload."""

    @model_validator(mode="before")
    @classmethod
    def absent_where_null(cls, data: JsonValue) -> JsonValue:
        """Treat a null service field like an omitted optional field."""
        if not isinstance(data, dict):
            return data
        return {name: value for name, value in data.items() if value is not None}


class ConversationReference(BaseModel, frozen=True):
    """An authenticated conversation URL or a public shared snapshot URL."""

    value: str

    def parsed(self) -> ParseResult:
        """This reference as a validated HTTPS ChatGPT URL."""
        supplied = self.value
        located = urlparse(supplied if "://" in supplied else f"https://{supplied}")
        host = (located.hostname or "").lower()
        if located.scheme != "https" or host not in {
            "chatgpt.com",
            "www.chatgpt.com",
            "chat.openai.com",
        }:
            raise ChatGPTDownloadError(
                "Expected an https://chatgpt.com/c/... or /share/... URL"
            )
        return located

    def route(self) -> str:
        """Whether this URL names a live conversation or a shared snapshot."""
        parts = PurePosixPath(self.parsed().path).parts
        if "share" in parts:
            return "share"
        if "c" in parts:
            return "conversation"
        raise ChatGPTDownloadError(
            "ChatGPT URL must contain /c/<conversation-id> or /share/<share-id>"
        )

    def identifier(self) -> str:
        """The service identifier following this URL's route segment."""
        parts = PurePosixPath(self.parsed().path).parts
        segment = "share" if self.route() == "share" else "c"
        position = parts.index(segment)
        if position + 1 >= len(parts):
            raise ChatGPTDownloadError(f"ChatGPT URL has no id after /{segment}/")
        identifier = parts[position + 1]
        if not identifier or not all(
            character.isalnum() or character in {"-", "_"} for character in identifier
        ):
            raise ChatGPTDownloadError("ChatGPT conversation id is malformed")
        return identifier

    def page_url(self) -> str:
        """The canonical page a browser opens for this reference."""
        return f"https://chatgpt.com/{'share' if self.route() == 'share' else 'c'}/{self.identifier()}"

    def api_urls(self) -> list[str]:
        """The web endpoints known to serve this page's complete payload."""
        identifier = quote(self.identifier(), safe="")
        if self.route() == "share":
            return [
                f"https://chatgpt.com/backend-api/share/{identifier}",
                f"https://chatgpt.com/backend-api/shared_conversation/{identifier}",
            ]
        return [f"https://chatgpt.com/backend-api/conversation/{identifier}"]


class ChatGPTAttachment(Payload, frozen=True):
    """One file referenced by a conversation message."""

    identifier: str = Field(default="", validation_alias=AliasChoices("id", "file_id"))
    name: str = Field(default="", validation_alias=AliasChoices("name", "file_name"))
    mime_type: str = ""
    size_bytes: int = Field(
        default=0, validation_alias=AliasChoices("size_bytes", "size")
    )
    download_url: str = ""

    def stored_name(self) -> str:
        """A single safe filename, with a useful fallback."""
        if "\x00" in self.name:
            raise ChatGPTDownloadError("Attachment filename contains a null byte")
        named = PurePosixPath(self.name).name
        if named:
            return named
        extension = mimetypes.guess_extension(self.mime_type) or ""
        return f"attachment{extension}"

    def relative_path(self) -> Path:
        """The collision-proof path this attachment occupies in a delivery."""
        if not self.identifier:
            raise ChatGPTDownloadError(
                f"Attachment {self.stored_name()!r} has no downloadable file id"
            )
        directory = PurePosixPath(self.identifier).name
        if directory != self.identifier or not all(
            character.isalnum() or character in {"-", "_"} for character in directory
        ):
            raise ChatGPTDownloadError("Attachment file id is not path-safe")
        return Path("attachments") / directory / self.stored_name()


class ChatGPTMetadata(Payload, frozen=True):
    """The message metadata fields needed to retain uploaded files."""

    attachments: list[ChatGPTAttachment] = []


class ChatGPTContent(Payload, frozen=True):
    """The typed envelope around one message's content parts."""

    content_type: str = ""
    parts: list[JsonValue] = []
    text: str = ""


class ChatGPTAuthor(Payload, frozen=True):
    """Who authored one ChatGPT message."""

    role: str = "unknown"


class ChatGPTMessage(Payload, frozen=True):
    """One node's message, including its attachment declarations."""

    id: str = ""
    author: ChatGPTAuthor = ChatGPTAuthor()
    content: ChatGPTContent = ChatGPTContent()
    metadata: ChatGPTMetadata = ChatGPTMetadata()


class ChatGPTNode(Payload, frozen=True):
    """One node in ChatGPT's branched conversation mapping."""

    id: str = ""
    parent: str | None = None
    children: list[str] = []
    message: ChatGPTMessage | None = None


class ChatGPTConversation(Payload, frozen=True):
    """The complete mapping and selected branch returned for one conversation."""

    title: str = ""
    create_time: float | None = None
    update_time: float | None = None
    mapping: dict[str, ChatGPTNode]
    current_node: str

    def active_messages(self) -> list[ChatGPTMessage]:
        """Messages on the selected branch, root to current node."""
        current = self.current_node
        visited: tuple[str, ...] = ()
        messages: tuple[ChatGPTMessage, ...] = ()
        while current:
            if current in visited:
                raise ChatGPTDownloadError("Conversation mapping contains a cycle")
            visited += (current,)
            if current not in self.mapping:
                raise ChatGPTDownloadError(
                    f"Conversation mapping omits active node {current}"
                )
            node = self.mapping[current]
            if node.message is not None:
                messages = (node.message, *messages)
            current = node.parent or ""
        if not messages:
            raise ChatGPTDownloadError("Conversation has no readable messages")
        return list(messages)

    def attachments(self) -> list[ChatGPTAttachment]:
        """Every distinct attachment anywhere in the complete mapping."""
        attachments = [
            attachment
            for node in self.mapping.values()
            if node.message is not None
            for attachment in node.message.metadata.attachments
        ]
        missing = next(
            (attachment for attachment in attachments if not attachment.identifier),
            None,
        )
        if missing is not None:
            raise ChatGPTDownloadError(
                f"Attachment {missing.stored_name()!r} has no file id"
            )
        return list({item.identifier: item for item in attachments}.values())


class AttachmentRecord(BaseModel, frozen=True):
    """The retained identity and digest of one downloaded file."""

    id: str
    name: str
    mime_type: str
    relative_path: str
    size_bytes: int
    sha256: str


class DownloadManifest(BaseModel, frozen=True):
    """A complete, replayable account of one retained ChatGPT delivery."""

    provider: str = "chatgpt"
    source_url: str
    fetched_at: str
    title: str
    route: str
    identifier: str
    active_message_count: int
    mapping_node_count: int
    attachments: list[AttachmentRecord]


class FetchedAttachment(BaseModel, frozen=True):
    """One attachment after its bytes have been fetched successfully."""

    declaration: ChatGPTAttachment
    body: bytes


def conversation_from(payload: JsonValue) -> ChatGPTConversation:
    """Find and validate the conversation object in a web response."""
    match payload:
        case {"mapping": dict()} as direct:
            candidate = direct
        case {"conversation": {"mapping": dict()} as nested}:
            candidate = nested
        case {"data": {"mapping": dict()} as nested}:
            candidate = nested
        case _:
            raise ChatGPTDownloadError(
                "ChatGPT returned no complete conversation mapping"
            )
    try:
        return ChatGPTConversation.model_validate(candidate)
    except ValueError as error:
        raise ChatGPTDownloadError(
            "ChatGPT conversation payload changed shape"
        ) from error


def attachment_marker(attachment: ChatGPTAttachment) -> str:
    """The transcript pointer to one retained attachment."""
    return (
        f"[Attachment: {attachment.stored_name()} → "
        f"{attachment.relative_path().as_posix()}]"
    )


def render_part(part: JsonValue) -> str:
    """One content part without silently dropping an unfamiliar shape."""
    if isinstance(part, str):
        return part
    if not isinstance(part, dict):
        return json.dumps(part, ensure_ascii=False)
    match part:
        case {"text": str() as text}:
            return text
        case {"asset_pointer": str() as pointer}:
            return f"[Asset: {pointer}]"
        case _:
            return (
                "```json\n" + json.dumps(part, indent=2, ensure_ascii=False) + "\n```"
            )


def render_message(message: ChatGPTMessage) -> str:
    """One speaker-tagged message plus the files it names."""
    content = [render_part(part) for part in message.content.parts]
    if message.content.text:
        content.append(message.content.text)
    content.extend(attachment_marker(item) for item in message.metadata.attachments)
    body = "\n\n".join(text for text in content if text)
    if not body:
        body = "[empty message payload; see conversation.json]"
    role = message.author.role or "unknown"
    return f"<{role}>\n{body}\n</{role}>"


def render_conversation(
    reference: ConversationReference, conversation: ChatGPTConversation
) -> str:
    """The selected branch as speaker-tagged Markdown beside the raw mapping."""
    title = conversation.title or "Untitled ChatGPT conversation"
    messages = "\n\n".join(
        render_message(message) for message in conversation.active_messages()
    )
    return (
        f"# {title}\n\n"
        f"Source: {reference.page_url()}\n\n"
        "The complete branched payload is in `conversation.json`; this file "
        "renders its selected branch.\n\n"
        f"{messages}\n"
    )


async def response_json(response: APIResponse) -> JsonValue:
    """Validate one Playwright response as JSON-shaped data."""
    try:
        return TypeAdapter(JsonValue).validate_python(await response.json())
    except (PlaywrightError, ValueError) as error:
        raise ChatGPTDownloadError(
            f"ChatGPT returned non-JSON data from {response.url}"
        ) from error


async def fetch_payload(
    request: APIRequestContext, reference: ConversationReference
) -> JsonValue:
    """Fetch one complete conversation through the browser's live session."""
    refusals: tuple[str, ...] = ()
    for url in reference.api_urls():
        response = await request.get(
            url,
            headers={"Referer": reference.page_url(), "Accept": "application/json"},
            fail_on_status_code=False,
        )
        if response.status == 200:
            return await response_json(response)
        refusals += (f"{response.status} from {url}",)
    if reference.route() == "conversation" and any(
        refusal.startswith(("401 ", "403 ", "404 ")) for refusal in refusals
    ):
        raise ChatGPTAuthenticationRequired(
            "The ChatGPT browser session is missing or expired"
        )
    route = "shared snapshot" if reference.route() == "share" else "conversation"
    recovery = " Check that the link is still available."
    raise ChatGPTDownloadError(
        f"ChatGPT refused the {route}: {', '.join(refusals)}.{recovery}"
    )


def allowed_download_url(value: str) -> str:
    """Accept only attachment URLs served by OpenAI-controlled origins."""
    absolute = urljoin("https://chatgpt.com", value)
    parsed = urlparse(absolute)
    host = (parsed.hostname or "").lower()
    allowed = any(
        host == suffix or host.endswith(f".{suffix}")
        for suffix in ("chatgpt.com", "openai.com", "oaiusercontent.com")
    )
    if parsed.scheme != "https" or not allowed:
        raise ChatGPTDownloadError(
            f"Attachment download escaped OpenAI-controlled origins: {absolute}"
        )
    return absolute


def redirected_download(payload: JsonValue) -> str | None:
    """A signed file URL returned by an attachment endpoint, when present."""
    match payload:
        case {"download_url": str() as target}:
            return target
        case {"url": str() as target}:
            return target
        case _:
            return None


async def attachment_response_body(
    request: APIRequestContext, response: APIResponse
) -> bytes:
    """Read an attachment response, following a JSON signed-URL envelope."""
    content_type = (
        response.headers["content-type"] if "content-type" in response.headers else ""
    )
    if "application/json" not in content_type:
        return await response.body()
    payload = await response_json(response)
    target = redirected_download(payload)
    if target is None:
        return await response.body()
    redirected = await request.get(
        allowed_download_url(target), fail_on_status_code=False
    )
    if redirected.status != 200:
        raise ChatGPTDownloadError(
            f"Signed attachment URL returned HTTP {redirected.status}"
        )
    return await redirected.body()


async def fetch_attachment(
    request: APIRequestContext, attachment: ChatGPTAttachment
) -> FetchedAttachment:
    """Download one declared attachment or fail the whole retention pass."""
    identifier = quote(attachment.identifier, safe="")
    candidates = [
        attachment.download_url,
        f"/backend-api/files/{identifier}/download",
        f"/backend-api/files/{identifier}",
    ]
    refusals: tuple[str, ...] = ()
    for candidate in candidates:
        if not candidate:
            continue
        url = allowed_download_url(candidate)
        response = await request.get(url, fail_on_status_code=False)
        if response.status == 200:
            body = await attachment_response_body(request, response)
            return FetchedAttachment(declaration=attachment, body=body)
        refusals += (f"HTTP {response.status} from {url}",)
    raise ChatGPTDownloadError(
        f"Could not download attachment {attachment.stored_name()!r}: "
        + "; ".join(refusals)
    )


def write_delivery(
    root: Path,
    reference: ConversationReference,
    raw: JsonValue,
    conversation: ChatGPTConversation,
    fetched: list[FetchedAttachment],
    output: Path | None = None,
) -> Path:
    """Atomically replace one retained conversation with a complete download."""
    expected = {item.identifier for item in conversation.attachments()}
    received = {item.declaration.identifier for item in fetched}
    if expected != received:
        raise ChatGPTDownloadError("Downloaded attachments do not match the payload")
    workspace = (
        (output if output is not None else root / "tmp" / "conversations") / "chatgpt"
    ).resolve()
    destination = workspace / reference.identifier()
    if not destination.resolve().is_relative_to(workspace):
        raise ChatGPTDownloadError(
            "Conversation destination escapes tmp/conversations/chatgpt"
        )
    workspace.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".chatgpt-staging-", dir=workspace
    ) as temporary:
        staged = Path(temporary) / reference.identifier()
        staged.mkdir(parents=True)
        (staged / "conversation.json").write_text(
            json.dumps(raw, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
        )
        (staged / "conversation.md").write_text(
            render_conversation(reference, conversation), encoding="utf-8"
        )
        records: tuple[AttachmentRecord, ...] = ()
        for item in fetched:
            path = staged / item.declaration.relative_path()
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(item.body)
            records += (
                AttachmentRecord(
                    id=item.declaration.identifier,
                    name=item.declaration.stored_name(),
                    mime_type=item.declaration.mime_type,
                    relative_path=item.declaration.relative_path().as_posix(),
                    size_bytes=len(item.body),
                    sha256=hashlib.sha256(item.body).hexdigest(),
                ),
            )
        manifest = DownloadManifest(
            source_url=reference.page_url(),
            fetched_at=datetime.now(UTC).isoformat(),
            title=conversation.title,
            route=reference.route(),
            identifier=reference.identifier(),
            active_message_count=len(conversation.active_messages()),
            mapping_node_count=len(conversation.mapping),
            attachments=list(records),
        )
        (staged / "manifest.json").write_text(
            manifest.model_dump_json(indent=2) + "\n", encoding="utf-8"
        )
        if destination.is_symlink():
            raise ChatGPTDownloadError("Conversation destination is a symlink")
        backup = Path(temporary) / "prior"
        if destination.exists():
            if not destination.is_dir():
                raise ChatGPTDownloadError(
                    "Conversation destination exists and is not a directory"
                )
            destination.rename(backup)
        try:
            staged.rename(destination)
        except OSError as error:
            if backup.exists():
                backup.rename(destination)
            raise ChatGPTDownloadError(
                "Could not install the complete ChatGPT delivery"
            ) from error
        if backup.exists():
            shutil.rmtree(backup)
    return destination


async def download_chatgpt(
    reference: ConversationReference, *, root: Path, directory: Path, output: Path
) -> Path:
    """Fetch, validate, and retain one conversation and every attachment."""
    async with browser_context(directory, headless=True) as context:
        raw = await fetch_payload(context.request, reference)
        conversation = conversation_from(raw)
        fetched = [
            await fetch_attachment(context.request, attachment)
            for attachment in conversation.attachments()
        ]
    return write_delivery(root, reference, raw, conversation, fetched, output)
