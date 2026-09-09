"""The frontend toolchain: a schema the types compile from, bundles owned like
every generated tree, and a page served from what was built.

The end-to-end build runs only where bun and the workspace's dependencies are
present, which is every machine that changes frontend code and the CI runner;
the rest is exercised over a bundle written by hand.
"""

import json
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from lup.harness.ownership import OWNERSHIP_FILENAME, load_manifest
from lup.web.build import source_digest, write_web_bundles
from lup.web.schema import view_schema, write_view_schema
from lup.web.serve import bundle_app

WORKSPACE = Path(__file__).resolve().parents[2] / "web"
"""The library's own bun workspace, beside this test's package."""


def test_the_view_schema_declares_every_view_model(tmp_path: Path) -> None:
    written = write_view_schema(Path("schema/views.json"), tmp_path)

    schema = json.loads(written.read_text(encoding="utf-8"))
    assert {"GraphView", "NodeDetail", "NodeView", "EdgeView"} <= set(schema["$defs"])
    assert write_view_schema(Path("schema/views.json"), tmp_path, check=True) == written
    written.write_text("{}\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="stale"):
        write_view_schema(Path("schema/views.json"), tmp_path, check=True)
    assert view_schema() == view_schema()


def handmade(root: Path, surface: str = "explorer") -> Path:
    """A bundle the way Vite lays one out, without Vite."""
    home = root / "bundles" / surface
    (home / "assets").mkdir(parents=True)
    (home / "index.html").write_text(
        '<!doctype html><script type="module" src="./assets/app.js"></script>\n',
        encoding="utf-8",
    )
    (home / "assets" / "app.js").write_text(
        "console.log('explorer');\n", encoding="utf-8"
    )
    return root / "bundles"


def test_bundle_app_serves_the_page_and_its_assets_by_name(tmp_path: Path) -> None:
    bundles = handmade(tmp_path)
    # The app answers only for the Host it was built for, which is the
    # loopback guard doing its job; the client has to speak that Host.
    client = TestClient(
        bundle_app("Explorer", "http://127.0.0.1:1", "explorer", bundles),
        base_url="http://127.0.0.1:1",
    )

    page = client.get("/")
    script = client.get("/assets/app.js")

    assert page.status_code == 200 and "assets/app.js" in page.text
    assert script.status_code == 200
    assert script.headers["content-type"].startswith("text/javascript")
    assert "explorer" in script.text
    assert client.get("/assets/missing.js").status_code == 404
    assert client.get("/assets/..%2Findex.html").status_code == 404


def test_a_missing_bundle_is_refused_naming_the_command(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="harness generate all"):
        bundle_app("Explorer", "http://127.0.0.1:1", "explorer", tmp_path / "none")


def test_source_digest_moves_with_the_sources_and_not_with_generated_types(
    tmp_path: Path,
) -> None:
    (tmp_path / "src" / "explorer").mkdir(parents=True)
    (tmp_path / "src" / "generated").mkdir()
    (tmp_path / "package.json").write_text("{}\n", encoding="utf-8")
    (tmp_path / "src" / "explorer" / "App.tsx").write_text("one", encoding="utf-8")
    before = source_digest(tmp_path)

    (tmp_path / "src" / "generated" / "views.d.ts").write_text("t", encoding="utf-8")
    assert source_digest(tmp_path) == before
    (tmp_path / "src" / "explorer" / "App.tsx").write_text("two", encoding="utf-8")
    assert source_digest(tmp_path) != before


@pytest.mark.skipif(
    shutil.which("bun") is None or not (WORKSPACE / "node_modules").is_dir(),
    reason="the frontend toolchain is not installed here",
)
def test_write_web_bundles_builds_owns_and_verifies(tmp_path: Path) -> None:
    """One build lands the tree with proof; a second changes nothing; a hand
    edit is stale; a source edit is stale."""
    bundles = Path("bundles")

    landed = write_web_bundles(WORKSPACE, bundles, ["explorer"], tmp_path)

    assert (landed / "explorer" / "index.html").is_file()
    manifest = load_manifest(landed / OWNERSHIP_FILENAME)
    assert manifest is not None and manifest.target_requirements == ["bun"]
    assert all(item.path.parts[0] == "bundles" for item in manifest.files)
    assert (
        write_web_bundles(WORKSPACE, bundles, ["explorer"], tmp_path, check=True)
        == landed
    )
    (landed / "explorer" / "index.html").write_text("edited\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="behind"):
        write_web_bundles(WORKSPACE, bundles, ["explorer"], tmp_path, check=True)


def test_a_workspace_without_dependencies_is_refused_naming_the_install(
    tmp_path: Path,
) -> None:
    (tmp_path / "web").mkdir()
    with pytest.raises(RuntimeError, match="bun install --frozen-lockfile"):
        write_web_bundles(Path("web"), Path("bundles"), ["explorer"], tmp_path)


def test_the_build_runs_where_the_proof_no_longer_holds_and_nowhere_else(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A holding proof is current in either mode; a check never builds."""
    workspace = tmp_path / "web"
    (workspace / "node_modules").mkdir(parents=True)
    (workspace / "src" / "explorer").mkdir(parents=True)
    (workspace / "package.json").write_text("{}\n", encoding="utf-8")
    source = workspace / "src" / "explorer" / "App.tsx"
    source.write_text("one", encoding="utf-8")
    builds: list[str] = []

    def built(home: Path, surface: str, out: Path) -> list[Path]:
        builds.append(surface)
        out.mkdir(parents=True, exist_ok=True)
        page = out / "index.html"
        page.write_text(f"<!doctype html>{surface}\n", encoding="utf-8")
        return [page]

    monkeypatch.setattr("lup.web.build.built_files", built)
    arguments = (Path("web"), Path("bundles"), ["explorer"], tmp_path)

    landed = write_web_bundles(*arguments)
    write_web_bundles(*arguments, check=True)
    write_web_bundles(*arguments)
    assert builds == ["explorer"]

    source.write_text("two", encoding="utf-8")
    with pytest.raises(RuntimeError, match="behind"):
        write_web_bundles(*arguments, check=True)
    assert builds == ["explorer"]
    write_web_bundles(*arguments)
    assert builds == ["explorer", "explorer"]

    (landed / "explorer" / "index.html").write_text("edited\n", encoding="utf-8")
    with pytest.raises(RuntimeError, match="behind"):
        write_web_bundles(*arguments, check=True)
    assert builds == ["explorer", "explorer"]
