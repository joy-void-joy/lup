"""Regression tests for devtools CLI bug fixes.

Each test pins a behavior that was broken in live testing: trace regexes
that did not match the emitted format, helpers that crashed on real data,
and arg construction that called nonexistent flags.
"""

from collections.abc import Iterator
from pathlib import Path

import pytest
import sh

from lup.paths import configure, project_root
from lup.trace import TraceLogger
from lup.types import LupTextBlock, LupToolResultBlock, LupToolUseBlock

ORIGINAL_ROOT = project_root()


@pytest.fixture
def isolated_root(tmp_path: Path) -> Iterator[Path]:
    configure(root=tmp_path, version="1.2.3")
    yield tmp_path
    configure(root=ORIGINAL_ROOT)


# ── fix 3: tool-call regex matches the real emitted trace format ──────────


def emitted_tool_trace() -> str:
    """Produce a trace via the real TraceLogger so the format is authoritative."""
    trace = TraceLogger(trace_path=Path("/tmp/unused.md"), title="t")
    trace.log_block(LupToolUseBlock(id="a", name="search", input={"q": "x"}))
    trace.log_block(LupToolResultBlock(tool_use_id="a", content="done"))
    trace.log_block(LupTextBlock(text="some prose, not a tool call"))
    return "\n".join(entry.content for entry in trace.entries)


class TestToolCallPattern:
    def test_matches_emitted_tool_and_result_headers(self) -> None:
        from lup_template.devtools.trace.traces import filter_tool_calls

        out = filter_tool_calls(emitted_tool_trace())

        assert "## 🔧 Tool: search" in out
        assert "## 📋 Result" in out

    def test_does_not_match_when_no_tool_blocks(self) -> None:
        from lup_template.devtools.trace.traces import filter_tool_calls

        prose = "# Trace\n\nJust some narrative text.\nNothing tool-shaped here.\n"
        assert filter_tool_calls(prose) == "(no tool call lines found)"


# ── fix 5: error scan windows the keyword and suppresses healthy JSON ─────


class TestErrorScan:
    def test_success_json_is_not_flagged(self) -> None:
        from lup_template.devtools.trace.traces import (
            ERROR_PATTERNS,
            SUCCESS_PATTERNS,
        )

        line = '{"status": "reviewed", "is_error": false, "error_count": 0}'
        # The naive error scan matches (contains "error")...
        assert ERROR_PATTERNS.search(line)
        # ...but the success guard suppresses it.
        assert SUCCESS_PATTERNS.search(line)

    def test_real_failure_is_flagged(self) -> None:
        from lup_template.devtools.trace.traces import (
            ERROR_PATTERNS,
            SUCCESS_PATTERNS,
        )

        line = 'Traceback: tool failed with "is_error": true'
        assert ERROR_PATTERNS.search(line)
        assert not SUCCESS_PATTERNS.search(line)

    def test_window_keeps_the_keyword_visible(self) -> None:
        from lup_template.devtools.trace.traces import keyword_window

        prefix = "x" * 300
        line = f"{prefix} the operation failed here {prefix}"
        window = keyword_window(line, width=40)

        assert "failed" in window
        assert len(window) <= 46  # width + ellipses


# ── fix 14: decode_stderr helper ──────────────────────────────────────────


class TestDecodeStderr:
    def test_decodes_bytes(self) -> None:
        from lup_template.devtools.utils import decode_stderr

        err = sh.ErrorReturnCode.__new__(sh.ErrorReturnCode)
        err.stderr = b"boom\n"
        assert decode_stderr(err) == "boom\n"

    def test_passes_through_str(self) -> None:
        from lup_template.devtools.utils import decode_stderr

        err = sh.ErrorReturnCode.__new__(sh.ErrorReturnCode)
        err.stderr = "already text"
        assert decode_stderr(err) == "already text"


# ── fix 9: remote parsing distinguishes https from scp/ssh ────────────────


class TestParseRemote:
    def test_https_remote_routes_to_https_scheme(self) -> None:
        from lup_template.devtools.dev.branches import parse_remote

        assert parse_remote("https://github.com/org/repo.git") == (
            "https",
            "github.com",
        )

    def test_scp_style_extracts_user_and_host(self) -> None:
        from lup_template.devtools.dev.branches import parse_remote

        assert parse_remote("git@github.com:org/repo.git") == ("ssh", "git@github.com")

    def test_ssh_scheme_extracts_user_and_host(self) -> None:
        from lup_template.devtools.dev.branches import parse_remote

        assert parse_remote("ssh://git@example.com/org/repo") == (
            "ssh",
            "git@example.com",
        )

    def test_local_path_is_not_a_remote(self) -> None:
        from lup_template.devtools.dev.branches import parse_remote

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

        captured: list[str] = []

        def fake_gh(*args: str) -> str:
            captured.extend(str(a) for a in args)
            return "https://github.com/org/repo/pull/42\n"

        monkeypatch.setattr(pr, "gh", fake_gh)

        results: list[pr.CreateResult] = []
        monkeypatch.setattr(pr, "output_result", lambda r, _as_json: results.append(r))

        pr.create(base="dev", title="feat: x", body="body", as_json=False)

        assert "--json" not in captured
        assert results[0].number == 42
        assert results[0].url == "https://github.com/org/repo/pull/42"

    def test_parse_pr_url_picks_url_line(self) -> None:
        from lup_template.devtools.dev.pr import parse_pr_url

        stdout = "Warning: 1 uncommitted change\nhttps://github.com/org/repo/pull/7\n"
        assert parse_pr_url(stdout) == "https://github.com/org/repo/pull/7"


# ── fix 15b: module-info filters to symbols defined in the module ──────────


class TestDefinedIn:
    def test_imported_class_excluded(self) -> None:
        from lup_template.devtools import py

        # py.py imports Path from pathlib; it is not defined there.
        assert not py.defined_in(py, "Path")

    def test_imported_module_excluded(self) -> None:
        from lup_template.devtools import py

        # py.py imports the inspect module; it is not defined there.
        assert not py.defined_in(py, "inspect")

    def test_locally_defined_function_included(self) -> None:
        from lup_template.devtools import py

        assert py.defined_in(py, "resolve_object")


# ── fix 16: feedback state tolerates tool_metrics: null ───────────────────


class TestToolMetricsNull:
    def write_session(self, root: Path, body: str) -> None:
        sdir = root / "notes" / "traces" / "1.2.3" / "sessions" / "s-null"
        sdir.mkdir(parents=True)
        (sdir / "result.json").write_text(body)

    def test_tools_does_not_crash_on_null_metrics(
        self, isolated_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from lup_template.devtools.feedback import state

        self.write_session(
            isolated_root,
            '{"session_id": "s-null", "timestamp": "2026-01-01T00:00:00", '
            '"tool_metrics": null}',
        )
        # Would raise AttributeError before the fix (None.get(...)).
        state.tools(version="1.2.3", all_versions=False, as_json=True)
        assert "Traceback" not in capsys.readouterr().err

    def test_errors_does_not_crash_on_null_metrics(
        self, isolated_root: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from lup_template.devtools.feedback import state

        self.write_session(
            isolated_root,
            '{"session_id": "s-null", "timestamp": "2026-01-01T00:00:00", '
            '"tool_metrics": null}',
        )
        state.errors(limit=10, version="1.2.3", all_versions=False, as_json=True)
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
        from lup_template.devtools.feedback.state import session_ids_from_status

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

        assert ids == {"sess with space", "sess-2"}

    def test_rename_source_is_discarded(self) -> None:
        from lup_template.devtools.feedback.state import session_ids_from_status

        root = Path("notes/traces")
        status = "\0".join(
            [
                "R  notes/traces/0.1.0/sessions/new-id/result.json",
                "notes/traces/0.1.0/sessions/old-id/result.json",
                "",
            ]
        )

        ids = session_ids_from_status(status, root)

        assert ids == {"new-id"}
