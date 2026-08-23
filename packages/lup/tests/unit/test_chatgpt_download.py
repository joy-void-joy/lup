"""Authenticated ChatGPT retention and its analysis-facing artifacts."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from lup.types import JsonValue
from lup.devtools.conversation import app as conversation
from lup.devtools.conversation import chatgpt


def sample_payload() -> JsonValue:
    """A selected branch, one discarded branch, and colliding filenames."""
    return {
        "title": "A useful discussion",
        "mapping": {
            "root": {
                "id": "root",
                "parent": None,
                "children": ["user", "branch"],
                "message": None,
            },
            "user": {
                "id": "user",
                "parent": "root",
                "children": ["assistant"],
                "message": {
                    "id": "message-user",
                    "author": {"role": "user"},
                    "content": {"content_type": "text", "parts": ["Question"]},
                    "metadata": {
                        "attachments": [
                            {
                                "id": "file-one",
                                "name": "../../notes.md",
                                "mime_type": "text/markdown",
                            }
                        ]
                    },
                },
            },
            "assistant": {
                "id": "assistant",
                "parent": "user",
                "children": [],
                "message": {
                    "id": "message-assistant",
                    "author": {"role": "assistant"},
                    "content": {
                        "content_type": "multimodal_text",
                        "parts": [
                            "Answer",
                            {"content_type": "code", "code": "result = 1"},
                        ],
                    },
                    "metadata": {},
                },
            },
            "branch": {
                "id": "branch",
                "parent": "root",
                "children": [],
                "message": {
                    "id": "message-branch",
                    "author": {"role": "assistant"},
                    "content": {"content_type": "text", "parts": ["Discarded"]},
                    "metadata": {
                        "attachments": [
                            {
                                "id": "file-two",
                                "name": "notes.md",
                                "mime_type": "text/markdown",
                            }
                        ]
                    },
                },
            },
        },
        "current_node": "assistant",
    }


def sample_conversation() -> chatgpt.ChatGPTConversation:
    """The validated form of :func:`sample_payload`."""
    return chatgpt.conversation_from(sample_payload())


@pytest.mark.parametrize(
    ("url", "route", "identifier"),
    [
        ("https://chatgpt.com/c/conversation-1", "conversation", "conversation-1"),
        ("chatgpt.com/g/g-test/c/conversation-2", "conversation", "conversation-2"),
        ("https://chat.openai.com/share/share-1", "share", "share-1"),
    ],
)
def test_reference_recognizes_authenticated_and_shared_urls(
    url: str, route: str, identifier: str
) -> None:
    reference = chatgpt.ConversationReference(value=url)

    assert reference.route() == route
    assert reference.identifier() == identifier


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/c/conversation-1",
        "https://chatgpt.com/",
        "https://chatgpt.com/c/../../escape",
    ],
)
def test_reference_refuses_urls_that_cannot_name_a_safe_delivery(url: str) -> None:
    with pytest.raises(chatgpt.ChatGPTDownloadError):
        chatgpt.ConversationReference(value=url).identifier()


def test_selected_branch_is_rendered_without_losing_unknown_content() -> None:
    reference = chatgpt.ConversationReference(
        value="https://chatgpt.com/c/conversation-1"
    )

    rendered = chatgpt.render_conversation(reference, sample_conversation())

    assert "<user>\nQuestion" in rendered
    assert "<assistant>\nAnswer" in rendered
    assert "result = 1" in rendered
    assert "Discarded" not in rendered
    assert "attachments/file-one/notes.md" in rendered
    assert "complete branched payload" in rendered


def test_every_branch_contributes_attachments_and_names_cannot_escape() -> None:
    attachments = sample_conversation().attachments()

    assert [item.identifier for item in attachments] == ["file-one", "file-two"]
    assert [item.relative_path().as_posix() for item in attachments] == [
        "attachments/file-one/notes.md",
        "attachments/file-two/notes.md",
    ]


def fetched_attachments() -> list[chatgpt.FetchedAttachment]:
    """Downloaded bytes for both declarations in the sample payload."""
    return [
        chatgpt.FetchedAttachment(declaration=declaration, body=body)
        for declaration, body in zip(
            sample_conversation().attachments(),
            (b"first attachment", b"second attachment"),
            strict=True,
        )
    ]


def test_delivery_keeps_raw_mapping_rendering_files_and_digests(tmp_path: Path) -> None:
    reference = chatgpt.ConversationReference(
        value="https://chatgpt.com/c/conversation-1"
    )
    destination = chatgpt.write_delivery(
        tmp_path,
        reference,
        sample_payload(),
        sample_conversation(),
        fetched_attachments(),
    )

    assert (destination / "conversation.json").is_file()
    assert "Question" in (destination / "conversation.md").read_text()
    assert (
        destination / "attachments" / "file-one" / "notes.md"
    ).read_bytes() == b"first attachment"
    manifest = chatgpt.DownloadManifest.model_validate_json(
        (destination / "manifest.json").read_text()
    )
    assert manifest.mapping_node_count == 4
    assert manifest.active_message_count == 2
    assert [record.size_bytes for record in manifest.attachments] == [
        16,
        17,
    ]
    assert all(len(record.sha256) == 64 for record in manifest.attachments)


def test_delivery_replaces_a_prior_complete_snapshot(tmp_path: Path) -> None:
    reference = chatgpt.ConversationReference(
        value="https://chatgpt.com/c/conversation-1"
    )
    destination = chatgpt.write_delivery(
        tmp_path,
        reference,
        sample_payload(),
        sample_conversation(),
        fetched_attachments(),
    )
    (destination / "stale.txt").write_text("old")

    rewritten = chatgpt.write_delivery(
        tmp_path,
        reference,
        sample_payload(),
        sample_conversation(),
        fetched_attachments(),
    )

    assert rewritten == destination
    assert not (rewritten / "stale.txt").exists()


def test_delivery_can_be_placed_under_a_caller_selected_output(tmp_path: Path) -> None:
    reference = chatgpt.ConversationReference(
        value="https://chatgpt.com/c/conversation-1"
    )

    destination = chatgpt.write_delivery(
        tmp_path,
        reference,
        sample_payload(),
        sample_conversation(),
        fetched_attachments(),
        tmp_path / "retained",
    )

    assert destination == tmp_path / "retained" / "chatgpt" / "conversation-1"


def test_delivery_refuses_to_look_complete_when_a_file_is_missing(
    tmp_path: Path,
) -> None:
    reference = chatgpt.ConversationReference(
        value="https://chatgpt.com/c/conversation-1"
    )

    with pytest.raises(chatgpt.ChatGPTDownloadError):
        chatgpt.write_delivery(
            tmp_path,
            reference,
            sample_payload(),
            sample_conversation(),
            fetched_attachments()[:1],
        )


def test_download_command_checkpoints_only_after_retention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkpoints: list[Path] = []

    async def download(
        url: str,
        root: Path,
        directories: conversation.BrowserDirectories,
        output: Path,
    ) -> Path:
        reference = chatgpt.ConversationReference(value=url)
        destination = output / "chatgpt" / reference.identifier()
        destination.mkdir(parents=True)
        return destination

    monkeypatch.setattr(conversation, "authenticated_chatgpt", download)
    monkeypatch.setattr(conversation, "project_root", lambda: tmp_path)
    monkeypatch.setattr(
        conversation,
        "checkpoint_delivery",
        lambda _root, destination, *, provider: checkpoints.append(destination),
    )

    result = CliRunner().invoke(
        conversation.app,
        [
            "chatgpt",
            "https://chatgpt.com/c/conversation-1",
            "--output",
            str(tmp_path / "retained"),
        ],
    )

    assert result.exit_code == 0
    assert checkpoints == [tmp_path / "retained" / "chatgpt" / "conversation-1"]
    assert "retained/chatgpt/conversation-1" in result.stdout


def test_attachment_redirects_stay_on_openai_controlled_origins() -> None:
    assert (
        chatgpt.allowed_download_url("https://files.oaiusercontent.com/file.bin")
        == "https://files.oaiusercontent.com/file.bin"
    )
    with pytest.raises(chatgpt.ChatGPTDownloadError):
        chatgpt.allowed_download_url("https://example.com/file.bin")
