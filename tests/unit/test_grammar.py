"""The typed AST grammar refines broad rules without weakening the hook.

`lup.codescan.grammar` decides a site by where its subject is declared, so
these exercise the three answers a type oracle can give — declared in the
family, declared outside it, and not resolvable — plus the hook's unchanged
line rule, the dead directives the refinement exposes, and the pyright client
that implements the port when one is installed.
"""

from pathlib import Path

from lup.codescan.antipatterns import PYTHON_ANTI_PATTERNS, audit_text
from lup.codescan.common import PythonSource
from lup.codescan.grammar import (
    GRAMMAR_RULES,
    GrammarRule,
    TypeFamily,
    attribute_call_sites,
    refute,
)
from lup.codescan.oracle import (
    DefinitionOracle,
    DefinitionSite,
    SourceBuffer,
    SourcePosition,
)
from lup.policy.bundle import bundled_antipattern_rows
from lup.policy.kernel.edit import antipattern_decision
from lup.policy.kernel.rows import AntiPatternRow

from lup.codeintel.client import utf16_column
from lup.devtools.dev.pyright_oracle import (
    PyrightOracle,
    locations_of,
)

MAPPING_STUB = """
class dict(MutableMapping[_KT, _VT]):
    def get(self, key): ...
"""

CLIENT_STUB = """
class Client(BaseClient):
    def get(self, url): ...
"""

MODULE_API_STUB = """
def get(url, **kwargs): ...


def post(url, **kwargs): ...
"""
"""What a module-qualified `httpx.get` resolves to: a `def` inside no class."""

STUB_DECLARATION_LINE = 3
"""The `def get` line in the two class stubs above."""

MODULE_DECLARATION_LINE = 2
"""The `def get` line in the module-level stub, which has no class to indent under."""


class TableOracle(DefinitionOracle):
    """Answers declaration queries from a table keyed by the queried line."""

    def __init__(self, answers: dict[int, list[DefinitionSite]]) -> None:
        self.answers = answers
        self.asked: list[SourcePosition] = []
        self.held: list[SourceBuffer] = []

    def definitions(
        self,
        positions: list[SourcePosition],
        buffers: list[SourceBuffer] | None = None,
    ) -> list[list[DefinitionSite]]:
        self.asked.extend(positions)
        self.held.extend(buffers or [])
        return [
            self.answers[position.line] if position.line in self.answers else []
            for position in positions
        ]


def stubs(tmp_path: Path) -> dict[str, DefinitionSite]:
    """Write every declaration the oracle can resolve a `get` into."""
    mapping = tmp_path / "builtins.pyi"
    mapping.write_text(MAPPING_STUB, encoding="utf-8")
    client = tmp_path / "_client.py"
    client.write_text(CLIENT_STUB, encoding="utf-8")
    api = tmp_path / "_api.py"
    api.write_text(MODULE_API_STUB, encoding="utf-8")
    return {
        "mapping": DefinitionSite(path=mapping, line=STUB_DECLARATION_LINE),
        "client": DefinitionSite(path=client, line=STUB_DECLARATION_LINE),
        "module": DefinitionSite(path=api, line=MODULE_DECLARATION_LINE),
    }


def source(text: str, name: str = "sample.py") -> PythonSource:
    return PythonSource(path=Path(name), module="sample", text=text)


def test_mapping_receiver_keeps_its_finding(tmp_path: Path) -> None:
    """A `.get` declared on `dict` is the schema-hiding access the rule means."""
    declaring = stubs(tmp_path)
    text = "value = payload.get('name')\n"
    refutations = refute(
        [source(text)], TableOracle({1: [declaring["mapping"]]}), GRAMMAR_RULES
    )
    assert refutations == {}
    findings = audit_text(text, PYTHON_ANTI_PATTERNS)
    assert [finding.rule_id for finding in findings] == ["dict-get"]


def test_non_mapping_receiver_is_refuted_with_evidence(tmp_path: Path) -> None:
    """A `.get` declared on an HTTP client is not what the rule is about."""
    declaring = stubs(tmp_path)
    text = "response = client.get('https://example.com')\n"
    refutations = refute(
        [source(text)], TableOracle({1: [declaring["client"]]}), GRAMMAR_RULES
    )
    refuted = refutations["sample.py"]
    assert [row.rule_id for row in refuted] == ["dict-get"]
    assert refuted[0].line == 1
    assert refuted[0].subject == "client"
    assert "`Client`" in refuted[0].evidence
    assert "outside the mapping family" in refuted[0].evidence
    assert audit_text(text, PYTHON_ANTI_PATTERNS, refuted) == []


def test_module_qualified_receiver_is_refuted_too(tmp_path: Path) -> None:
    """`httpx.get` is the same evidence as `client.get`, declared without a class.

    Reading only the declaring class left this with no origin at all, which is
    what the engine gets for a symbol the checker could not resolve — so the
    finding stood while every bare-variable sibling in the same run was
    refuted. It could not be cleared from either side: the rule text says a
    directive on a resolved non-mapping receiver is reported spurious, and
    rewriting it to a bare variable trips the edit hook, which judges a
    fragment with no oracle to resolve anything.
    """
    declaring = stubs(tmp_path)
    text = "response = httpx.get('https://example.com')\n"
    refutations = refute(
        [source(text)], TableOracle({1: [declaring["module"]]}), GRAMMAR_RULES
    )
    refuted = refutations["sample.py"]
    assert [row.rule_id for row in refuted] == ["dict-get"]
    assert refuted[0].subject == "httpx"
    assert "the module-level `get`" in refuted[0].evidence
    assert "outside the mapping family" in refuted[0].evidence
    assert audit_text(text, PYTHON_ANTI_PATTERNS, refuted) == []


def test_a_declaration_that_is_neither_resolves_nothing(tmp_path: Path) -> None:
    """A site that is no declaration must not be read as one outside the family.

    Refuting on "not a class" alone would clear a finding whenever the checker
    pointed anywhere this cannot read — which is the broad rule's job to keep,
    not the refinement's to take away.
    """
    assignment = tmp_path / "constants.py"
    assignment.write_text("get = 1\n", encoding="utf-8")
    text = "value = payload.get('name')\n"
    answers = {1: [DefinitionSite(path=assignment, line=1)]}

    assert refute([source(text)], TableOracle(answers), GRAMMAR_RULES) == {}


def test_unresolved_receiver_keeps_the_broad_verdict(tmp_path: Path) -> None:
    """A receiver the checker cannot resolve is no evidence, so nothing drops."""
    stubs(tmp_path)
    text = "value = whatever.get('name')\n"
    assert refute([source(text)], TableOracle({}), GRAMMAR_RULES) == {}


def test_the_oracle_is_told_the_text_being_audited(tmp_path: Path) -> None:
    """What is resolved has to be what is audited, or the answer is about
    another file that happens to share the path.

    The gap only opens where a caller holds text disk does not — an edit
    judged before it is written — which is the caller whose verdict most
    depends on the resolution being about its own content.
    """
    declaring = stubs(tmp_path)
    text = "response = client.get('https://example.com')\n"
    oracle = TableOracle({1: [declaring["client"]]})

    refute([source(text)], oracle, GRAMMAR_RULES)

    assert [(held.path.as_posix(), held.text) for held in oracle.held] == [
        ("sample.py", text)
    ]


def test_absent_oracle_degrades_to_the_broad_rule() -> None:
    """With no checker installed the grammar refutes nothing at all."""
    text = "response = client.get('https://example.com')\n"
    assert refute([source(text)], None, GRAMMAR_RULES) == {}
    findings = audit_text(text, PYTHON_ANTI_PATTERNS)
    assert [finding.rule_id for finding in findings] == ["dict-get"]


def test_one_mapping_among_clients_keeps_the_line(tmp_path: Path) -> None:
    """A line refutes only when every site on it does."""
    declaring = stubs(tmp_path)
    text = "value = client.get(payload.get('url'))\n"
    refutations = refute(
        [source(text)],
        TableOracle({1: [declaring["client"], declaring["mapping"]]}),
        GRAMMAR_RULES,
    )
    assert refutations == {}


def test_refuted_line_reports_its_directive_as_spurious(tmp_path: Path) -> None:
    """The ninety-seven reflex suppressions become dead directives on evidence."""
    declaring = stubs(tmp_path)
    text = "response = client.get(url)  # lup: ignore[dict-get]\n"
    refuted = refute(
        [source(text)], TableOracle({1: [declaring["client"]]}), GRAMMAR_RULES
    )["sample.py"]
    findings = audit_text(text, PYTHON_ANTI_PATTERNS, refuted)
    assert [finding.kind for finding in findings] == ["spurious"]
    assert findings[0].rule_id == "dict-get"


def test_unparseable_source_refutes_nothing(tmp_path: Path) -> None:
    """Text the grammar cannot parse keeps the regex pass's verdicts."""
    stubs(tmp_path)
    text = "response = client.get(\n"
    assert refute([source(text)], TableOracle({}), GRAMMAR_RULES) == {}


def test_engine_carries_a_rule_it_was_not_written_for(tmp_path: Path) -> None:
    """A new rule is a selector and a family, not a change to the engine."""
    declaring = stubs(tmp_path)
    rule = GrammarRule(
        id="string-replace",
        select=attribute_call_sites("replace"),
        family=TypeFamily(name="text", classes=["str"]),
        refinement="only text receivers are string surgery",
    )
    text = "renamed = target.replace('a', 'b')\n"
    refuted = refute([source(text)], TableOracle({1: [declaring["client"]]}), [rule])
    assert [row.rule_id for row in refuted["sample.py"]] == ["string-replace"]


def test_query_lands_on_the_attribute_not_the_receiver(tmp_path: Path) -> None:
    """The resolved symbol is `get` itself: its declaration names the class."""
    stubs(tmp_path)
    oracle = TableOracle({})
    refute([source("value = payload.get('name')\n")], oracle, GRAMMAR_RULES)
    assert [(position.line, position.column) for position in oracle.asked] == [(1, 16)]


def test_the_hook_row_declares_that_its_verdict_needs_a_declaration() -> None:
    """The regex is unchanged; what the gate does when it fires is not.

    A rule the grammar sharpens cannot be decided from an edit alone, and the
    row says so rather than leaving the gate to state a verdict the audit
    contradicts. Derived from `GRAMMAR_RULES` rather than declared beside it,
    so a rule that gains or loses a refinement cannot disagree with the row
    describing it.
    """
    rows = [row for row in bundled_antipattern_rows()[".py"] if row["id"] == "dict-get"]
    assert rows == [
        AntiPatternRow(
            id="dict-get",
            pattern=r"\.get\s*\(",
            message=rows[0]["message"],
            context="code",
            refiner="dict_get_exempt_lines",
            strength="soft",
            resolution="required",
        )
    ]


def test_an_unrefined_rule_declares_no_resolution() -> None:
    """Only the rules the grammar sharpens carry the ask-instead-of-deny path.

    Every other rule decides from the text in front of it, so nothing about
    them is pending a checker, and widening the field to all of them would
    turn each into an approval question nobody can answer better than the
    gate already did.
    """
    rows = bundled_antipattern_rows()[".py"]
    refined = {rule.id for rule in GRAMMAR_RULES}
    assert {row["id"] for row in rows if row["resolution"] == "required"} == refined


def test_the_gate_asks_where_nothing_resolved_the_receiver() -> None:
    """Told nothing, the gate says so instead of stating the audit's opposite.

    This is the deadlock's own shape: the kernel denied `client.get(url)` and
    demanded a directive, the audit resolved `Client`, refuted the finding,
    and reported that directive spurious. No version of the file passed both.
    """
    rows = bundled_antipattern_rows()[".py"]

    decision = antipattern_decision(
        None, "response = client.get(url)\n", rows, python_source=True
    )

    assert decision is not None and decision.effect == "ask"
    assert "could not resolve" in decision.reason


def test_a_resolved_receiver_is_admitted_without_a_directive() -> None:
    """The answer the audit already gives, reaching the gate that refused it.

    Refuted here means the same edit needs no marker at all — which is what
    the rule's own text tells an author to write, and what the gate could not
    admit while it had no way to know.
    """
    rows = bundled_antipattern_rows()[".py"]

    decision = antipattern_decision(
        None,
        "response = client.get(url)\n",
        rows,
        python_source=True,
        refuted={"dict-get": [1]},
    )

    assert decision is None or decision.effect == "allow"


def test_an_unresolved_verdict_still_denies_a_rule_that_needs_no_checker() -> None:
    """The ask reaches exactly the rules whose verdict was pending, and no others.

    A rule decided from the text in front of it gains nothing from a checker,
    so an absent one must not soften it — otherwise every gate in the table
    degrades together the moment a language server is missing.
    """
    rows = bundled_antipattern_rows()[".py"]

    decision = antipattern_decision(None, "import re\n", rows, python_source=True)

    assert decision is not None and decision.effect == "deny"


def test_client_converts_byte_columns_to_protocol_units() -> None:
    """`ast` counts UTF-8 bytes where LSP counts UTF-16 units."""
    line = "wrapped = ünïcøde.get(key)"
    assert utf16_column(line, len("wrapped = ünïcøde".encode())) == 17


def test_client_decodes_every_specified_result_shape(tmp_path: Path) -> None:
    """A bare Location, a list, null, and an unspecified shape all decode."""
    declared = tmp_path / "stub.pyi"
    location = {
        "uri": declared.as_uri(),
        "range": {"start": {"line": 6, "character": 8}},
    }
    assert locations_of(location) == [DefinitionSite(path=declared, line=7)]
    assert (
        locations_of([location, location])
        == [DefinitionSite(path=declared, line=7)] * 2
    )
    assert locations_of(None) == []
    assert locations_of({"targetUri": declared.as_uri()}) == []


def test_absent_language_server_answers_unresolved(tmp_path: Path) -> None:
    """A checker that will not start is no evidence, so the sweep still runs."""
    oracle = PyrightOracle(tmp_path / "not-installed", tmp_path)
    positions = [SourcePosition(path=tmp_path / "sample.py", line=1, column=0)]
    assert oracle.definitions(positions) == [[]]
    assert oracle.definitions([]) == []
