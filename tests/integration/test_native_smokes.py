"""Live smokes for the four historically fragile native boundaries.

These tests execute installed provider CLIs and incur real model calls. The
scheduled native lane supplies credentials and deliberately cheap models.
"""

import os
import shutil
from pathlib import Path

import pytest
import sh
from pydantic import BaseModel, ConfigDict, Field

from lup.adapters.claude.harness import ClaudeSpellings
from lup.adapters.claude.runtime import (
    ClaudeSessionConfig,
    create_claude_session_factory,
)
from lup.adapters.codex.harness_runtime import CodexPluginInstaller, PluginCacheConfig
from lup.adapters.codex.runtime import CodexSessionConfig, create_codex_session_factory
from lup.harness.process import LocalProcessLauncher
from lup.resolver.contracts import QuestionBroker
from lup.resolver.core import ResolverCore
from lup.resolver.models import (
    AnswerBatch,
    InventoryNote,
    QuestionAnswer,
    QuestionBatch,
    ResolveRequest,
    ResolverConfig,
    SourceSnapshot,
    VerificationCommand,
)
from lup.runtime.contracts import SessionFactory
from lup.runtime.models import TurnInput, TurnTextBlock, turn_request

pytestmark = pytest.mark.integration

CLAUDE_SMOKE_MODEL = "claude-haiku-4-5-20251001"
CODEX_SMOKE_MODEL = "gpt-5.5"


async def test_fresh_claude_session_completes_one_turn(tmp_path: Path) -> None:
    """A fresh native session id survives one complete turn."""
    factory = create_claude_session_factory(
        ClaudeSessionConfig(
            model=CLAUDE_SMOKE_MODEL,
            system_prompt="Answer in one short sentence.",
            cwd=tmp_path,
            max_turns=1,
        )
    )
    async with factory.open() as handle:
        accepted = await handle.session.start(
            turn_request(TurnInput(text="Reply with the single word: ready"))
        )
        result = await accepted.turn.result()

    assert result.identifiers.session.value
    assert result.identifiers.turn.value
    texts = [block.text for block in result.blocks if isinstance(block, TurnTextBlock)]
    assert any("ready" in text.lower() for text in texts)
    assert result.usage.output_tokens > 0


class SmokeSubmission(BaseModel):
    """Typed output carried by the dynamic tool on ``thread/start``."""

    message: str = Field(min_length=1)


async def test_codex_thread_start_carries_a_dynamic_tool(tmp_path: Path) -> None:
    """A typed binding survives the installed app-server schema."""
    factory = create_codex_session_factory(
        CodexSessionConfig(
            model=CODEX_SMOKE_MODEL,
            developer_instructions="Follow the submission instruction exactly.",
            cwd=tmp_path,
            sandbox="read-only",
            approval_policy="never",
        )
    )
    async with factory.open() as handle:
        accepted = await handle.session.start(
            turn_request(
                TurnInput(
                    text=(
                        "Submit your output now: call the submission tool with "
                        "message set to 'smoke ok'."
                    )
                ),
                SmokeSubmission,
            )
        )
        result = await accepted.turn.result()

    assert result.output.message
    assert result.identifiers.session.value


class ScriptedQuestionBroker(QuestionBroker):
    """Answer every persisted resolver question with its recommendation."""

    def __init__(self) -> None:
        self.asked: list[QuestionBatch] = []

    async def ask(self, questions: QuestionBatch) -> AnswerBatch:
        self.asked.append(questions)
        answers = [
            QuestionAnswer(
                question_id=question.id,
                value=question.recommendation
                or (question.choices[0] if question.choices else "yes"),
            )
            for question in questions.questions
        ]
        return AnswerBatch(run_id=questions.run_id, answers=answers)


def fixture_repository(root: Path) -> Path:
    """Create a throwaway repository carrying one review note."""
    repo = root / "fixture-repo"
    repo.mkdir()
    git = sh.Command("git")
    git("init", "--initial-branch=main", _cwd=repo)
    git("config", "user.email", "smoke@example.invalid", _cwd=repo)
    git("config", "user.name", "Native Smoke", _cwd=repo)
    module = repo / "greeting.py"
    module.write_text(
        '# lup: rename GREETING_TEXT to WELCOME_TEXT\nGREETING_TEXT = "hello"\n',
        encoding="utf-8",
    )
    git("add", ".", _cwd=repo)
    git("commit", "-m", "chore: seed fixture", _cwd=repo)
    return repo


async def test_miniature_resolver_run_on_a_fixture_repository(tmp_path: Path) -> None:
    """The resolver process boundary captures plain, unpaged output."""
    repo = fixture_repository(tmp_path)
    launcher = LocalProcessLauncher()
    run_id = "smoke-run"

    def worker_factory(cwd: Path) -> SessionFactory:
        return create_claude_session_factory(
            ClaudeSessionConfig(
                model=CLAUDE_SMOKE_MODEL,
                system_prompt="Execute the persisted Lup resolver assignment.",
                cwd=cwd,
                add_dirs=[cwd],
            )
        )

    def reviewer_factory(cwd: Path) -> SessionFactory:
        return create_claude_session_factory(
            ClaudeSessionConfig(
                model=CLAUDE_SMOKE_MODEL,
                system_prompt="Independently review the persisted resolver change.",
                cwd=cwd,
                add_dirs=[cwd],
            )
        )

    from lup_template.devtools.harness.catalog import portable_harness

    core = ResolverCore(
        ResolverConfig(
            state_root=repo / ".lup" / "resolve",
            workspace=repo,
            worktree_root=tmp_path / f"fixture-repo-resolve-{run_id}",
            run_id=run_id,
            integration_branch=f"resolve/{run_id}/review",
            verification_commands=[
                VerificationCommand(name="status", arguments=["git", "status"])
            ],
        ),
        portable_harness().resolver,
        worker_factory,
        reviewer_factory,
        ClaudeSpellings(),
        ScriptedQuestionBroker(),
        launcher,
    )
    head = str(sh.Command("git")("rev-parse", "HEAD", _cwd=repo)).strip()
    manifest = await core.run(
        ResolveRequest(
            source=SourceSnapshot(branch="main", commit=head),
            notes=[
                InventoryNote(
                    file=Path("greeting.py"),
                    line=1,
                    text="rename GREETING_TEXT to WELCOME_TEXT",
                    context='GREETING_TEXT = "hello"',
                )
            ],
        )
    )

    assert manifest.run_id == run_id
    assert manifest.review_branch
    branches = str(sh.Command("git")("branch", "--list", _cwd=repo))
    assert manifest.review_branch in branches


class CodexEditFixture(BaseModel):
    """Paths participating in the blocked-edit smoke."""

    model_config = ConfigDict(frozen=True)

    repository: Path
    module: Path


def codex_edit_fixture(root: Path) -> CodexEditFixture:
    """Create a repository whose requested edit violates the Lup policy."""
    repo = root / "codex-edit-fixture"
    repo.mkdir()
    sh.Command("git")("init", "--initial-branch=main", _cwd=repo)
    module = repo / "module.py"
    module.write_text('VALUE = "safe"\n', encoding="utf-8")
    return CodexEditFixture(repository=repo, module=module)


def test_codex_plugin_blocks_a_forbidden_apply_patch(tmp_path: Path) -> None:
    """A denied plugin hook keeps the file unchanged and the session alive."""
    root = Path.cwd()
    codex_home = tmp_path / "codex-home"
    # The isolated home keeps plugin state out of the user's config but must
    # still carry credentials — codex reads auth only from its CODEX_HOME.
    auth = Path.home() / ".codex" / "auth.json"
    if auth.exists():
        codex_home.mkdir(parents=True)
        shutil.copy(auth, codex_home / "auth.json")
    from lup_template.devtools.harness.catalog import portable_harness

    plugin = portable_harness().plugins[0]
    CodexPluginInstaller(
        PluginCacheConfig(codex_home=codex_home, marketplace=plugin.marketplace)
    ).ensure(
        root / ".codex" / "plugins" / plugin.name,
        root,
    )
    fixture = codex_edit_fixture(tmp_path)
    final_message = tmp_path / "codex-final.txt"
    environment = {
        **os.environ,  # lup: ignore[os-environ] — preserve provider credentials
        "CODEX_HOME": str(codex_home),
    }
    prompt = (
        "Use apply_patch exactly once to add `import re` and a call to "
        "`re.search` to module.py. Do not use any other tool. The Lup hook must "
        "reject that anti-pattern; after the rejection reply exactly hook-blocked."
    )

    # No --ignore-user-config: plugins (and their hooks) are recorded in the
    # isolated home's config.toml, which that flag would silently discard.
    sh.Command("codex")(
        "exec",
        "--enable",
        "hooks",
        "--dangerously-bypass-hook-trust",
        "--ephemeral",
        "--sandbox",
        "workspace-write",
        "--model",
        CODEX_SMOKE_MODEL,
        "--output-last-message",
        str(final_message),
        "--cd",
        str(fixture.repository),
        prompt,
        _env=environment,
    )

    assert fixture.module.read_text(encoding="utf-8") == 'VALUE = "safe"\n'
    assert final_message.read_text(encoding="utf-8").strip() == "hook-blocked"
