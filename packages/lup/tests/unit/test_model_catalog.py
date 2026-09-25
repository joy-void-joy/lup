"""Each runtime's model lineup, read from its CLI and compiled into types.

Three claims, each one a place the lineup could drift from what a session
accepts: the readers take the CLI's own report apart correctly, the compiled
module says exactly what its committed snapshot says, and a lineup that moved
is reported as the names that moved rather than as a byte difference.
"""

import json
from pathlib import Path

import pytest

from lup.devtools.dev.model_catalog import (
    CatalogDrift,
    CatalogSource,
    library_catalogs,
    write_model_catalog,
)
from lup.providers.catalog import CatalogAlias, CatalogModel, ModelCatalog
from lup.providers.claude.catalog import (
    BAKED_CATALOG_MARKER,
    BakedCatalog,
    baked_catalog,
    script_literal,
)
from lup.providers.codex.catalog import CodexCatalogReport
from lup.workspace.paths import project_root

# The shape the Claude Code bundler emits for its baked catalog: unquoted
# keys, `!0`/`!1` booleans, exponent numbers, and the data file's own
# comment key opening it. Trimmed to the fields a lineup reads.
BAKED = (
    b'var x=1;var u2n={"//":"Hand-maintained baked-in model catalog \\u2014 '
    b'the source of truth.",schema_version:1,models:['
    b'{id:"claude-haiku-4-5",family:"haiku",provider_ids:{first_party:'
    b'"claude-haiku-4-5-20251001",bedrock:null},context:{window:2e5,'
    b'supports_1m_suffix:!0},capabilities:["context_management"]},'
    b'{id:"claude-opus-4-6",family:"opus",provider_ids:{first_party:'
    b'"claude-opus-4-6"},context:{window:1e6,native_1m:!0},capabilities:'
    b'["effort","max_effort"]},'
    b'{id:"claude-opus-5-5",family:"opus",provider_ids:{first_party:'
    b'"claude-opus-5-5"},context:{window:1e6,supports_1m_suffix:!0},'
    b'capabilities:["effort","max_effort","xhigh_effort"],fast:!1}],'
    b'aliases:{opus:{default:"claude-opus-5-5",per_provider:{foundry:'
    b'"claude-opus-4-6"}},haiku:{default:"claude-haiku-4-5"}},best:"opus",'
    b"alias_migration:{}};function next(){return void 0}"
)


def test_the_literal_reader_takes_the_bundler_dialect() -> None:
    parsed = script_literal(BAKED, BAKED.find(BAKED_CATALOG_MARKER))

    assert isinstance(parsed, dict)
    assert parsed["schema_version"] == 1
    models = parsed["models"]
    assert isinstance(models, list)
    first = models[0]
    assert isinstance(first, dict)
    assert first["context"] == {"window": 200000, "supports_1m_suffix": True}
    assert first["provider_ids"] == {
        "first_party": "claude-haiku-4-5-20251001",
        "bedrock": None,
    }


def test_the_literal_reader_refuses_what_it_does_not_know() -> None:
    """A token outside the data subset is refused, never guessed at."""
    program = b'{"//":"Hand-maintained baked-in model catalog",x:f(1)}'
    with pytest.raises(ValueError, match="where a value was expected"):
        script_literal(program, 0)


def test_a_claude_lineup_names_every_spelling_the_cli_resolves() -> None:
    lineup = BakedCatalog.model_validate(
        script_literal(BAKED, BAKED.find(BAKED_CATALOG_MARKER))
    ).lineup("2.1.282 (Claude Code)")

    assert lineup.names() == [
        "opus",
        "haiku",
        "best",
        "claude-haiku-4-5-20251001",
        "opus[1m]",
        "haiku[1m]",
        "best[1m]",
        "claude-haiku-4-5[1m]",
        "claude-opus-5-5[1m]",
        "claude-haiku-4-5",
        "claude-opus-4-6",
        "claude-opus-5-5",
    ]
    assert lineup.efforts() == ["low", "medium", "high", "xhigh", "max", "ultra"]
    assert lineup.efforts_of("claude-haiku-4-5") == []
    assert lineup.efforts_of("claude-opus-4-6") == ["low", "medium", "high", "max"]
    # An alias answers every route it can take: the foundry route's model
    # lacks xhigh, the default's has it, and refusing it would refuse the
    # route that works.
    assert lineup.efforts_of("opus") == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ]
    assert lineup.efforts_of("best") == lineup.efforts_of("opus")


def test_the_installed_claude_program_is_read_the_same_way(tmp_path: Path) -> None:
    program = tmp_path / "claude"
    program.write_bytes(b"\x7fELF binary prefix " + BAKED + b" trailing code")

    assert baked_catalog(program).best == "opus"


def test_a_program_without_a_baked_catalog_says_so(tmp_path: Path) -> None:
    program = tmp_path / "claude"
    program.write_bytes(b"no catalog here")

    with pytest.raises(ValueError, match="carries no baked model catalog"):
        baked_catalog(program)


def test_a_codex_report_keeps_each_models_own_efforts() -> None:
    report = CodexCatalogReport.model_validate_json(
        json.dumps(
            {
                "models": [
                    {
                        "slug": "gpt-6-astra",
                        "display_name": "GPT-6-Astra",
                        "supported_reasoning_levels": [
                            {"effort": effort, "description": ""}
                            for effort in ["low", "xhigh", "max", "ultra"]
                        ],
                        "base_instructions": "ignored",
                    },
                    {
                        "slug": "gpt-5.5",
                        "supported_reasoning_levels": [
                            {"effort": "low"},
                            {"effort": "xhigh"},
                        ],
                    },
                ]
            }
        )
    )
    lineup = report.lineup("codex-cli 0.156.1")

    assert lineup.names() == ["gpt-6-astra", "gpt-5.5"]
    assert lineup.efforts_of("gpt-5.5") == ["low", "xhigh"]
    assert lineup.efforts() == ["low", "xhigh", "max", "ultra"]


def test_a_ladder_the_models_disagree_about_is_refused() -> None:
    """Two models ordering the same two rungs oppositely leave no ladder."""
    contradictory = ModelCatalog(
        runtime="codex",
        observed="",
        models=[
            CatalogModel(id="a", efforts=["low", "high"]),
            CatalogModel(id="b", efforts=["high", "low"]),
        ],
    )
    with pytest.raises(ValueError, match="disagree about the order"):
        contradictory.efforts()


def lineup(*models: CatalogModel) -> ModelCatalog:
    return ModelCatalog(runtime="codex", observed="codex-cli 1", models=list(models))


def test_drift_names_what_moved_and_ignores_the_version() -> None:
    committed = lineup(
        CatalogModel(id="kept", efforts=["low"]),
        CatalogModel(id="retired", efforts=["low"]),
        CatalogModel(id="widened", efforts=["low"]),
    )
    live = lineup(
        CatalogModel(id="kept", efforts=["low"]),
        CatalogModel(id="widened", efforts=["low", "max"]),
        CatalogModel(id="new", efforts=["low"]),
    ).model_copy(update={"observed": "codex-cli 2"})

    drift = CatalogDrift.between(committed, live)

    assert drift.added == ["new"]
    assert drift.removed == ["retired"]
    assert drift.changed == ["widened: ['low'] -> ['low', 'max']"]
    assert not drift.settled()
    assert CatalogDrift.between(committed, committed).settled()
    assert CatalogDrift.between(
        committed, committed.model_copy(update={"observed": "codex-cli 9"})
    ).settled()


def test_a_module_behind_its_snapshot_is_stale(tmp_path: Path) -> None:
    source = CatalogSource(runtime="codex", directory=Path("providers/codex"))
    snapshot = tmp_path / source.snapshot()
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        lineup(CatalogModel(id="gpt-a", efforts=["low", "high"])).text(),
        encoding="utf-8",
    )

    written = write_model_catalog(source, tmp_path)
    assert "type CodexModel = Literal[" in written.read_text(encoding="utf-8")
    assert '"gpt-a": ["low", "high"],' in written.read_text(encoding="utf-8")
    write_model_catalog(source, tmp_path, check=True)

    snapshot.write_text(
        lineup(CatalogModel(id="gpt-b", efforts=["low"])).text(), encoding="utf-8"
    )
    with pytest.raises(RuntimeError, match="stale"):
        write_model_catalog(source, tmp_path, check=True)


def test_a_long_row_is_written_the_way_the_formatter_keeps_it(tmp_path: Path) -> None:
    source = CatalogSource(runtime="claude", directory=Path("providers/claude"))
    name = "claude-a-model-name-long-enough-to-overflow-one-line-20260101"
    snapshot = tmp_path / source.snapshot()
    snapshot.parent.mkdir(parents=True)
    snapshot.write_text(
        ModelCatalog(
            runtime="claude",
            observed="1",
            models=[CatalogModel(id=name, efforts=["low", "medium", "high"])],
            aliases=[CatalogAlias(name="short", targets=[name])],
        ).text(),
        encoding="utf-8",
    )

    text = write_model_catalog(source, tmp_path).read_text(encoding="utf-8")

    assert f'    "{name}": [\n        "low",\n' in text
    assert '    "short": ["low", "medium", "high"],\n' in text


@pytest.mark.parametrize(
    "source", library_catalogs(), ids=lambda source: source.runtime
)
def test_the_committed_modules_say_what_their_snapshots_say(
    source: CatalogSource,
) -> None:
    """The offline half of the drift check, which needs no CLI installed."""
    write_model_catalog(source, project_root(), check=True)
