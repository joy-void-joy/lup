"""Render a /lup:resolve run's manifest into one static HTML review page.

The execute workflow returns a manifest — one entry per concern with the
editor's summary, the verifier's verdict, and per-note findings. This module
joins that manifest with each branch's diff against the snapshot base and
renders a single self-contained page (inline CSS, no external assets), so the
human gate can read every concern's implementation before approving merges.
Exposed as ``lup-devtools dev resolve-review``.
"""

import html
import json
from pathlib import Path

import typer
from pydantic import BaseModel, Field, ValidationError

from lup_template.devtools.utils import git

CSS = """
body { font: 15px/1.5 system-ui, sans-serif; margin: 0; background: #f6f8fa; color: #1f2328; }
main { max-width: 1100px; margin: 0 auto; padding: 24px 16px 80px; }
h1 { font-size: 26px; } h2 { font-size: 20px; margin: 0 0 4px; }
section.concern { background: #fff; border: 1px solid #d1d9e0; border-radius: 8px; padding: 20px 24px; margin: 24px 0; }
.badges { margin: 6px 0 12px; }
.badge { display: inline-block; border-radius: 12px; padding: 2px 10px; font-size: 12px; font-weight: 600; margin-right: 6px; }
.ok { background: #dafbe1; color: #116329; }
.warn { background: #fff8c5; color: #7d4e00; }
.info { background: #ddf4ff; color: #0969da; }
.spec { color: #59636e; font-size: 13.5px; white-space: pre-wrap; background: #f6f8fa; border-radius: 6px; padding: 10px 12px; }
table.notes { border-collapse: collapse; width: 100%; margin: 12px 0; font-size: 13.5px; }
table.notes th, table.notes td { border: 1px solid #d1d9e0; padding: 6px 10px; vertical-align: top; text-align: left; }
table.notes th { background: #f6f8fa; }
td.note-loc { white-space: nowrap; font-family: monospace; font-size: 12px; }
.residual { background: #fff8c5; border: 1px solid #d4a72c66; border-radius: 6px; padding: 8px 12px; font-size: 13.5px; }
.filelist { font-family: monospace; font-size: 12px; color: #59636e; }
pre { background: #f6f8fa; border: 1px solid #d1d9e0; border-radius: 6px; padding: 10px; overflow-x: auto; font-size: 12px; line-height: 1.45; }
pre.diff { background: #fff; }
.add { color: #116329; background: #e6ffec; display: inline-block; width: 100%; }
.del { color: #82071e; background: #ffebe9; display: inline-block; width: 100%; }
.hunk { color: #0969da; font-weight: 600; }
.fhead { color: #6639ba; font-weight: 700; }
details > summary { cursor: pointer; color: #0969da; font-weight: 600; margin: 8px 0; }
.meta-box { background: #fff; border: 1px solid #d1d9e0; border-radius: 8px; padding: 16px 24px; margin: 16px 0; }
code { background: #eff1f3; border-radius: 4px; padding: 1px 4px; font-size: 0.9em; }
"""


class NoteRef(BaseModel):
    file: str
    line: int
    text: str


class NoteFinding(BaseModel):
    file: str
    line: int
    addressed: bool
    how: str


class ManifestEntry(BaseModel):
    """One concern's outcome, as returned by the execute workflow."""

    id: str
    title: str
    spec: str = ""
    branch: str | None = None
    committed: bool = False
    accepted: bool = False
    generalized: bool = False
    reason: str = ""
    residual: str = ""
    summary: str = ""
    files_changed: list[str] = Field(default_factory=list)
    swept_beyond_scope: list[str] = Field(default_factory=list)
    note_findings: list[NoteFinding] = Field(default_factory=list)
    notes: list[NoteRef] = Field(default_factory=list)


def load_manifest(path: Path) -> list[ManifestEntry]:
    """Read a manifest from a workflow task-output file or a bare JSON list.

    Accepts the three shapes a resolve run produces: the raw manifest array,
    ``{"manifest": [...]}``, and the task-output envelope
    ``{"result": {"manifest": [...]}}``.
    """
    parsed = json.loads(path.read_text(encoding="utf-8"))
    match parsed:
        case list():
            raw = parsed
        case {"manifest": list() as entries}:
            raw = entries
        case {"result": {"manifest": list() as entries}}:
            raw = entries
        case _:
            raise typer.BadParameter(f"No manifest array found in {path}")
    try:
        return [ManifestEntry.model_validate(entry) for entry in raw]
    except ValidationError as e:
        raise typer.BadParameter(f"Manifest entry does not validate: {e}") from e


def render_diff(text: str) -> str:
    rendered: list[str] = []  # lup: ignore[empty-collection] — html fold
    for line in text.splitlines():
        esc = html.escape(line)
        if line.startswith(
            ("diff --git", "index ", "+++", "---", "new file", "deleted file")
        ):
            rendered.append(f'<span class="fhead">{esc}</span>')
        elif line.startswith("@@"):
            rendered.append(f'<span class="hunk">{esc}</span>')
        elif line.startswith("+"):
            rendered.append(f'<span class="add">{esc}</span>')
        elif line.startswith("-"):
            rendered.append(f'<span class="del">{esc}</span>')
        else:
            rendered.append(esc)
    return "\n".join(rendered)


def finding_for(entry: ManifestEntry, note: NoteRef) -> NoteFinding:
    for finding in entry.note_findings:
        if finding.file == note.file and finding.line == note.line:
            return finding
    return NoteFinding(
        file=note.file,
        line=note.line,
        addressed=False,
        how="(verifier recorded no finding for this note)",
    )


def render_concern(entry: ManifestEntry, base: str) -> str:
    branch = entry.branch or "(none)"
    badges: list[str] = []  # lup: ignore[empty-collection] — badge assembly
    badges.append(
        '<span class="badge ok">verifier: accepted</span>'
        if entry.accepted
        else '<span class="badge warn">verifier: doubted</span>'
    )
    if entry.generalized:
        badges.append('<span class="badge ok">generalized</span>')
    badges.append(
        f'<span class="badge info">{html.escape(branch)}</span>'
        if entry.committed
        else '<span class="badge warn">no commit</span>'
    )

    rows: list[str] = []  # lup: ignore[empty-collection] — html fold
    for note in entry.notes:
        finding = finding_for(entry, note)
        state = "✅" if finding.addressed else "⚠️"
        rows.append(
            "<tr>"
            f'<td class="note-loc">{html.escape(note.file)}:{note.line}</td>'
            f"<td>{html.escape(note.text)}</td>"
            f"<td>{state} {html.escape(finding.how)}</td>"
            "</tr>"
        )
    notes_table = (
        '<table class="notes">'
        "<tr><th>Original note</th><th>Text</th><th>How it was addressed</th></tr>"
        + "".join(rows)
        + "</table>"
    )

    if entry.committed:
        stat = str(git("diff", "--stat", f"{base}...{branch}"))
        diff = str(git("diff", f"{base}...{branch}"))
    else:
        stat = "(no commit — no diff)"
        diff = ""

    files = ", ".join(entry.files_changed)
    swept = ", ".join(entry.swept_beyond_scope)
    swept_html = (
        "<p class='filelist'><strong>Swept beyond declared scope:</strong> "
        f"{html.escape(swept)}</p>"
        if swept
        else ""
    )
    residual_html = (
        f"<div class='residual'><strong>Residual:</strong> {html.escape(entry.residual)}</div>"
        if entry.residual
        else ""
    )

    return f"""
<section class="concern" id="{html.escape(entry.id)}">
<h2>{html.escape(entry.title)}</h2>
<div class="badges">{"".join(badges)}</div>
<details><summary>Generalized spec (what the editor was told)</summary>
<div class="spec">{html.escape(entry.spec)}</div></details>
{notes_table}
<p><strong>Editor summary:</strong> {html.escape(entry.summary)}</p>
<p class="filelist"><strong>Files changed:</strong> {html.escape(files)}</p>
{swept_html}
<p><strong>Verifier reason:</strong> {html.escape(entry.reason)}</p>
{residual_html}
<pre>{html.escape(stat)}</pre>
<details><summary>Full diff vs {html.escape(base[:7])}</summary>
<pre class="diff">{render_diff(diff)}</pre></details>
</section>
"""


def build_review(manifest_path: Path, base: str, out: Path, intro: Path | None) -> None:
    """Assemble and write the review page (the ``resolve-review`` command)."""
    entries = load_manifest(manifest_path)
    ordered = sorted(entries, key=lambda e: (not e.accepted, not e.committed))
    accepted = sum(1 for e in entries if e.accepted)
    committed = sum(1 for e in entries if e.committed)
    intro_html = (
        f'<div class="meta-box">{intro.read_text(encoding="utf-8")}</div>'
        if intro
        else ""
    )
    header = (
        f"<h1>/lup:resolve review — base <code>{html.escape(base[:7])}</code></h1>"
        f'<div class="meta-box"><p><strong>{len(entries)} concerns</strong>: '
        f"{committed} committed, {accepted} verifier-accepted. Nothing is merged "
        "yet — approval at the gate merges a concern's branch and thereby clears "
        "its notes.</p></div>"
    )
    sections = "".join(render_concern(entry, base) for entry in ordered)
    page = (
        "<!doctype html><html><head><meta charset='utf-8'>"
        "<title>lup resolve review</title>"
        f"<style>{CSS}</style></head><body><main>"
        f"{header}{intro_html}{sections}"
        "</main></body></html>"
    )
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    typer.echo(f"wrote {out} ({len(page)} bytes, {len(entries)} concerns)")
