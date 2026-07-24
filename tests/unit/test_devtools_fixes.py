# lup: ignore[tuple-shape]
# Test fixtures and assertions construct these shapes deliberately.
"""Regression tests for devtools CLI bug fixes.

Each test pins a behavior that was broken in live testing: trace regexes
that did not match the emitted format, helpers that crashed on real data,
and arg construction that called nonexistent flags.
"""

import ast
from collections.abc import Iterator
from pathlib import Path

import pytest
import sh

from lup.telemetry.trace import TraceLogger
from lup.workspace.paths import configure, project_root
from lup.types import LupTextBlock, LupToolResultBlock, LupToolUseBlock

ORIGINAL_ROOT = project_root()


@pytest.fixture
def isolated_root(tmp_path: Path) -> Iterator[Path]:
    configure(root=tmp_path, version="1.2.3")
    yield tmp_path
    configure(root=ORIGINAL_ROOT)


# ── fix 3: the tool-call view renders typed events, not grepped markdown ──


class TestToolCallView:
    def test_renders_calls_from_the_events_sidecar(self, tmp_path: Path) -> None:
        from lup_template.devtools.trace.traces import render_tool_calls

        trace_path = tmp_path / "t.md"
        trace = TraceLogger(trace_path=trace_path, title="t")
        trace.log_block(LupToolUseBlock(id="a", name="search", input={"q": "x"}))
        trace.log_block(LupToolResultBlock(tool_use_id="a", content="done"))
        trace.log_block(LupTextBlock(text="some prose, not a tool call"))

        out = render_tool_calls(trace_path)

        assert "✓ search" in out
        assert "prose" not in out

    def test_no_tool_calls_recorded(self, tmp_path: Path) -> None:
        from lup_template.devtools.trace.traces import render_tool_calls

        trace_path = tmp_path / "t.md"
        trace = TraceLogger(trace_path=trace_path, title="t")
        trace.log_block(LupTextBlock(text="Just some narrative text."))
        trace.save()

        assert render_tool_calls(trace_path) == "(no tool calls recorded)"


# ── fix 5: legacy-markdown error scan reads is_error, not keywords ─────────


def legacy_trace(result_content: str) -> str:
    """A legacy .md trace (no sidecar) with one tool call and result."""
    trace = TraceLogger(trace_path=Path("/tmp/unused.md"), title="t")
    trace.log_block(LupToolUseBlock(id="a", name="search", input={"q": "x"}))
    trace.log_block(LupToolResultBlock(tool_use_id="a", content=result_content))
    return "\n".join(entry.content for entry in trace.entries)


class TestLegacyMarkdownErrorScan:
    """The structured path is primary; this pins the legacy-.md fallback.

    A healthy result and a failing result both contain the word "error"
    (``"is_error": false`` vs ``true``); only parsing the JSON tells them
    apart, which a keyword scan could not.
    """

    def test_healthy_result_is_not_an_error(self) -> None:
        from lup_template.devtools.trace.traces import events_from_legacy_markdown

        events = events_from_legacy_markdown(
            legacy_trace('{"status": "reviewed", "is_error": false}')
        )

        assert [e.kind for e in events if e.kind == "error"] == []
        call = next(e for e in events if e.kind == "tool_call")
        assert call.tool == "search" and call.ok is True

    def test_failing_result_emits_error_paired_to_its_tool(self) -> None:
        from lup_template.devtools.trace.traces import events_from_legacy_markdown

        events = events_from_legacy_markdown(
            legacy_trace('{"is_error": true, "content": "boom"}')
        )

        error = next(e for e in events if e.kind == "error")
        assert error.tool == "search"

    def test_capability_phrasing_in_response_text(self) -> None:
        from lup_template.devtools.trace.traces import events_from_legacy_markdown

        trace = TraceLogger(trace_path=Path("/tmp/unused.md"), title="t")
        trace.log_block(LupTextBlock(text="A tool that searches PyPI would be useful."))
        content = "\n".join(e.content for e in trace.entries)

        events = events_from_legacy_markdown(content)
        assert any(e.kind == "capability_request" for e in events)


# ── fix 14: decode_stderr helper ──────────────────────────────────────────


class TestDecodeStderr:
    def test_decodes_bytes_and_trims_framing(self) -> None:
        from lup_template.devtools.utils import decode_stderr

        err = sh.ErrorReturnCode.__new__(sh.ErrorReturnCode)
        err.stderr = b"boom\n"
        assert decode_stderr(err) == "boom"

    def test_passes_through_str(self) -> None:
        from lup_template.devtools.utils import decode_stderr

        err = sh.ErrorReturnCode.__new__(sh.ErrorReturnCode)
        err.stderr = "already text"
        assert decode_stderr(err) == "already text"


# ── fix 9: remote parsing distinguishes https from scp/ssh ────────────────


class TestParseRemote:
    def test_https_remote_routes_to_https_scheme(self) -> None:
        from lup_template.devtools.dev.remote_auth import RemoteRef, parse_remote

        assert parse_remote("https://github.com/org/repo.git") == RemoteRef(
            scheme="https", destination="github.com"
        )

    def test_scp_style_extracts_user_and_host(self) -> None:
        from lup_template.devtools.dev.remote_auth import RemoteRef, parse_remote

        assert parse_remote("git@github.com:org/repo.git") == RemoteRef(
            scheme="ssh", destination="git@github.com"
        )

    def test_ssh_scheme_extracts_user_and_host(self) -> None:
        from lup_template.devtools.dev.remote_auth import RemoteRef, parse_remote

        assert parse_remote("ssh://git@example.com/org/repo") == RemoteRef(
            scheme="ssh", destination="git@example.com"
        )

    def test_local_path_is_not_a_remote(self) -> None:
        from lup_template.devtools.dev.remote_auth import parse_remote

        assert parse_remote("/srv/git/repo.git") is None


# ── fix 13: rebase uses REBASE_HEAD, not CHERRY_PICK_HEAD ──────────────────


class TestTheirsRef:
    def test_rebase_uses_rebase_head(self) -> None:
        from lup_template.devtools.dev.conflicts import theirs_ref_for

        assert theirs_ref_for("rebase") == "REBASE_HEAD"

    def test_merge_uses_merge_head(self) -> None:
        from lup_template.devtools.dev.conflicts import theirs_ref_for

        assert theirs_ref_for("merge") == "MERGE_HEAD"

    def test_cherry_pick_uses_cherry_pick_head(self) -> None:
        from lup_template.devtools.dev.conflicts import theirs_ref_for

        assert theirs_ref_for("cherry-pick") == "CHERRY_PICK_HEAD"


# ── fix 1: pr create no longer passes --json; URL/number parsed from stdout ─


class TestPrCreate:
    def test_create_does_not_call_gh_with_json(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import lup_template.devtools.dev.pr as pr

        calls: list[tuple[str, ...]] = []

        class FakeGh:
            def out(self, *args: str) -> str:
                calls.append(tuple(str(a) for a in args))
                return "https://github.com/org/repo/pull/42"

        monkeypatch.setattr(pr, "gh", FakeGh())

        results: list[pr.CreateResult] = []
        monkeypatch.setattr(pr, "output_result", lambda r, _as_json: results.append(r))

        pr.create(base="dev", title="feat: x", body="body", as_json=False)

        assert len(calls) == 1, "URL parsing must not need a second gh call"
        assert "--json" not in calls[0]
        assert results[0].number == 42
        assert results[0].url == "https://github.com/org/repo/pull/42"

    def test_parse_pr_url_picks_url_line(self) -> None:
        from lup_template.devtools.dev.pr import parse_pr_url

        stdout = "Warning: 1 uncommitted change\nhttps://github.com/org/repo/pull/7\n"
        assert parse_pr_url(stdout) == "https://github.com/org/repo/pull/7"


# ── fix 15b: module-info filters to symbols defined in the module ──────────


class TestDefinedIn:
    def test_imported_class_excluded(self) -> None:
        from lup_template.devtools.py import common, info

        # common.py imports Path from pathlib; it is not defined there.
        assert not info.defined_in(common, "Path")

    def test_imported_module_excluded(self) -> None:
        from lup_template.devtools.py import common, info

        # common.py imports the importlib module; it is not defined there.
        assert not info.defined_in(common, "importlib")

    def test_locally_defined_function_included(self) -> None:
        from lup_template.devtools.py import common, info

        assert info.defined_in(common, "resolve_object")


# ── fix 16: feedback state tolerates tool_metrics: null ───────────────────


class TestToolMetricsNull:
    def write_session(self, root: Path, body: str) -> None:
        sdir = root / "notes" / "traces" / "1.2.3" / "sessions" / "s-null"
        sdir.mkdir(parents=True)
        (sdir / "result.json").write_text(body)

    def test_tools_does_not_crash_on_null_metrics(
        self, isolated_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from lup_template.devtools.feedback import reports

        self.write_session(
            isolated_root,
            '{"session_id": "s-null", "timestamp": "2026-01-01T00:00:00", '
            '"tool_metrics": null}',
        )
        # Would raise AttributeError before the fix (None.get(...)).
        reports.tools(version="1.2.3", all_versions=False, as_json=True)
        assert "Traceback" not in capsys.readouterr().err

    def test_errors_does_not_crash_on_null_metrics(
        self, isolated_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from lup_template.devtools.feedback import reports

        self.write_session(
            isolated_root,
            '{"session_id": "s-null", "timestamp": "2026-01-01T00:00:00", '
            '"tool_metrics": null}',
        )
        reports.errors(limit=10, version="1.2.3", all_versions=False, as_json=True)
        assert "Traceback" not in capsys.readouterr().err


# ── fix 17: write_env_local preserves comments/order ──────────────────────


class TestWriteEnvLocal:
    def test_preserves_comments_and_updates_in_place(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import lup_template.devtools.setup as setup

        env_file = tmp_path / ".env.local"
        env_file.write_text(
            "# my secrets\nAPI_KEY=old\n\n# trailing comment\nKEEP=yes\n"
        )
        monkeypatch.setattr(setup, "ENV_LOCAL", env_file)

        setup.write_env_local({"API_KEY": "new", "NEW_KEY": "added"})

        text = env_file.read_text()
        assert "# my secrets" in text
        assert "# trailing comment" in text
        assert "API_KEY=new" in text
        assert "API_KEY=old" not in text
        assert "KEEP=yes" in text
        assert "NEW_KEY=added" in text
        # Existing key updated in place, before the appended new key.
        assert text.index("API_KEY=new") < text.index("NEW_KEY=added")


# ── fix: porcelain -z parsing anchored on the configured trace root ───────


class TestSessionIdsFromStatus:
    def test_versioned_layout_and_root_anchoring(self) -> None:
        from lup_template.devtools.feedback.commits import session_ids_from_status

        root = Path("notes/traces")
        status = "\0".join(
            [
                " M notes/traces/0.1.0/sessions/sess with space/result.json",
                "?? notes/traces/0.2.0/logs/sess-2/trace.md",
                "?? notes/other/sessions/ignored/x.json",
                "?? unrelated.py",
                "",
            ]
        )

        ids = session_ids_from_status(status, root)

        assert ids == ["sess with space", "sess-2"]

    def test_rename_source_is_discarded(self) -> None:
        from lup_template.devtools.feedback.commits import session_ids_from_status

        root = Path("notes/traces")
        status = "\0".join(
            [
                "R  notes/traces/0.1.0/sessions/new-id/result.json",
                "notes/traces/0.1.0/sessions/old-id/result.json",
                "",
            ]
        )

        ids = session_ids_from_status(status, root)

        assert ids == ["new-id"]


# ── fix: worktree pulls are fast-forward-only ─────────────────────────────


class TestWorktreePullsAreFastForwardOnly:
    """A bare ``git pull`` obeys ``pull.rebase`` and can rewrite history.

    Under ``pull.rebase=true`` against a stale base, it replays the whole
    branch onto the remote default and strands the worktree mid-rebase
    while the caller only logs a warning and reports success. ``--ff-only``
    fails clean with the working tree untouched, so every pull carries it.
    """

    def test_every_pull_call_site_passes_ff_only(self) -> None:
        from lup_template.devtools.dev import pr

        tree = ast.parse(Path(pr.__file__).read_text(encoding="utf-8"))
        pulls = [
            call
            for call in ast.walk(tree)
            if isinstance(call, ast.Call)
            if any(
                isinstance(arg, ast.Constant) and arg.value == "pull"
                for arg in call.args
            )
        ]

        assert pulls, "no pull call site found in dev.pr"
        for call in pulls:
            flags = [arg.value for arg in call.args if isinstance(arg, ast.Constant)]
            assert "--ff-only" in flags, (
                f"dev/pr.py:{call.lineno} pulls without --ff-only"
            )
