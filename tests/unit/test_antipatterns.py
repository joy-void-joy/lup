# lup: ignore
"""The anti-pattern set is single-sourced, and the auditor agrees with the hook.

`lup.codescan.antipatterns` is the importable source of truth; the edit hook carries
a generated copy inline because it cannot import on its hot path. These tests pin
that the committed mirror equals `lup-devtools dev gen-hook`'s output (so it can
never drift) and that the auditor flags the two classes the hook cannot catch
after the fact: a match with no marker, and a marker guarding nothing.
"""

import importlib.util
import re

from lup.codescan.antipatterns import (
    PYTHON_ANTI_PATTERNS,
    TS_ANTI_PATTERNS,
    AntiPattern,
    audit_text,
)
from lup_template.devtools.dev.gen_hook import HOOK_PATH, render_hook_text

spec = importlib.util.spec_from_file_location("auto_allow_edits", HOOK_PATH)
assert spec is not None and spec.loader is not None
hook = importlib.util.module_from_spec(spec)
spec.loader.exec_module(hook)


def lib_rows(patterns: list[AntiPattern]) -> list[tuple[str, str, str]]:
    return [(ap.id, ap.pattern.pattern, ap.message) for ap in patterns]


def hook_rows(
    table: list[tuple[str, re.Pattern[str], str]],
) -> list[tuple[str, str, str]]:
    return [(rule_id, pattern.pattern, message) for rule_id, pattern, message in table]


def test_python_table_matches_hook() -> None:
    """The committed hook equals `dev gen-hook`'s output — regenerate after editing a rule."""
    assert render_hook_text() == HOOK_PATH.read_text(encoding="utf-8")


def test_ts_table_matches_hook() -> None:
    """The library TS table is identical to the hook's inline copy (ids too)."""
    hook_table: list[tuple[str, re.Pattern[str], str]] = hook.TS_ANTI_PATTERNS
    assert lib_rows(TS_ANTI_PATTERNS) == hook_rows(hook_table)


def test_rule_ids_are_unique_kebab_case() -> None:
    """Every rule id is a distinct kebab-case token a typed ignore can target."""
    for table in (PYTHON_ANTI_PATTERNS, TS_ANTI_PATTERNS):
        ids = [ap.id for ap in table]
        assert len(ids) == len(set(ids))
        for rule_id in ids:
            assert re.fullmatch(r"[a-z][a-z0-9-]*", rule_id), rule_id


def test_audit_flags_unguarded_match() -> None:
    findings = audit_text("x: Any = 1\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].line == 1


def test_audit_flags_bare_ignore_as_untyped() -> None:
    # A bare `# lup: ignore` still silences the rule (stays valid) but is
    # surfaced as "untyped" so the migration to typed directives is gradual;
    # the message names the rule it should narrow to.
    findings = audit_text("x: Any = 1  # lup: ignore\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["untyped"]
    assert "any-type" in findings[0].message


def test_audit_typed_ignore_silences_exactly_its_rule() -> None:
    findings = audit_text("x: Any = 1  # lup: ignore[any-type]\n", PYTHON_ANTI_PATTERNS)
    assert findings == []


def test_audit_typed_ignore_naming_wrong_rule_still_flags() -> None:
    # Names tuple-shape, but the line trips any-type: the real hit is missing
    # and the tuple-shape directive guards nothing (spurious).
    findings = audit_text(
        "x: Any = 1  # lup: ignore[tuple-shape]\n", PYTHON_ANTI_PATTERNS
    )
    kinds = {f.kind for f in findings}
    assert kinds == {"missing", "spurious"}


def test_audit_flags_spurious_bare_marker() -> None:
    findings = audit_text("x: int = 1  # lup: ignore\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["spurious"]


def test_audit_flags_typed_ignore_guarding_nothing() -> None:
    findings = audit_text(
        "x: int = 1  # lup: ignore[tuple-shape]\n", PYTHON_ANTI_PATTERNS
    )
    assert [f.kind for f in findings] == ["spurious"]
    assert "tuple-shape" in findings[0].message


def test_audit_leaves_foreign_scanner_ids_alone() -> None:
    # seam-boundary belongs to the boundary scan; the auditor owns no rule
    # by that id and must not call its typed ignore spurious.
    foreign = "import x.claude  # lup: ignore[seam-boundary]\n"
    assert audit_text(foreign, PYTHON_ANTI_PATTERNS) == []

    unowned = "import x.claude  # lup: ignore[no-such-rule]\n"
    assert [f.kind for f in audit_text(unowned, PYTHON_ANTI_PATTERNS)] == ["spurious"]


def test_audit_skips_file_level_ignore() -> None:
    findings = audit_text("# lup: ignore\nx: Any = 1\n", PYTHON_ANTI_PATTERNS)
    assert findings == []


def test_audit_skips_plain_comment_lines() -> None:
    findings = audit_text("# a comment mentioning Any in prose\n", PYTHON_ANTI_PATTERNS)
    assert findings == []


def test_atomic_renames_are_exempt_from_replace_rule() -> None:
    # Path-receiver `.replace` is an atomic rename, not string surgery, so the
    # string-replace rule leaves it alone. (os.replace is redirected to
    # os-file-ops — see test_audit_flags_os_file_ops_and_environ.)
    source = "tmp_path.replace(target)\nPath.replace(a, b)\n"
    assert audit_text(source, PYTHON_ANTI_PATTERNS) == []


def test_string_replace_still_flagged() -> None:
    findings = audit_text('name.replace("-", "_")\n', PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]


def test_bare_split_is_exempt_from_split_rule() -> None:
    assert audit_text("fields = raw.split()\n", PYTHON_ANTI_PATTERNS) == []


def test_split_on_separator_still_flagged() -> None:
    findings = audit_text('parts = raw.split(",")\n', PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]


def test_docstring_mention_of_ignore_is_not_a_guard() -> None:
    source = '"""Audit `# lup: ignore` markers."""\nx = 1\n'
    assert audit_text(source, PYTHON_ANTI_PATTERNS) == []


def test_ignore_inside_string_literal_is_not_a_guard() -> None:
    source = 'fixture = "x: Any = 1  # lup: ignore"\n'
    findings = audit_text(source, PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]


def test_note_quoting_ignore_is_not_a_guard() -> None:
    source = "x = 1  # lup: should we remove every # lup: ignore?\n"
    assert audit_text(source, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_strip_like_split() -> None:
    findings = audit_text("name = raw.strip()\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert ".strip()" in findings[0].message


def test_audit_flags_string_keyed_dict_annotation() -> None:
    findings = audit_text("env: dict[str, str]\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].rule_id == "dict-str-payload"


def test_audit_accepts_non_string_keyed_dict() -> None:
    assert audit_text("counts: dict[int, str]\n", PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_bare_object_annotations() -> None:
    for line in (
        "def probe(value: object) -> None: ...\n",
        "def load() -> object: ...\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert [f.kind for f in findings] == ["missing"], line
        assert "object" in findings[0].message


def test_audit_accepts_underscore_object_params() -> None:
    line = "def handler(_context: object) -> None: ...\n"
    assert audit_text(line, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_bare_basemodel_annotations() -> None:
    for line in (
        "def show(result: BaseModel, as_json: bool) -> None: ...\n",
        "def load() -> BaseModel: ...\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert [f.kind for f in findings] == ["missing"], line
        assert "concrete union" in findings[0].message


def test_audit_accepts_basemodel_bounds_and_unions() -> None:
    clean = (
        "def read[T: BaseModel](model: type[T]) -> T | None: ...\n"
        "class Tool[I: BaseModel, O: BaseModel]: ...\n"
        "def dump(data: BaseModel | Sequence[int]) -> None: ...\n"
    )
    assert audit_text(clean, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_typing_and_stdlib_modernization() -> None:
    for line, needle in (
        ("x: Optional[int] = None\n", "PEP 604"),
        ("pairs: Union[int, str] = 1\n", "PEP 604"),
        ("items: List[str]\n", "lowercase builtin"),
        ("base = os.path.dirname(p)\n", "pathlib.Path"),
        ("value = eval(expr)\n", "eval()"),
        ("os.system('ls')\n", "`sh` library"),
        ("now = datetime.utcnow()\n", "naive"),
        ("def bump() -> None:\n    global counter\n", "`global`"),
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert [f.kind for f in findings] == ["missing"], line
        assert needle in findings[0].message, line


def test_audit_accepts_prefixed_eval_and_method_calls() -> None:
    clean = "value = ast.literal_eval(expr)\nglobal_config = 1\n"
    assert audit_text(clean, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_ts_additions() -> None:
    for line in (
        "const name = user!.name;\n",
        "var total = 0;\n",
        "let cb: Function;\n",
        "console.log('debug');\n",
    ):
        findings = audit_text(line, TS_ANTI_PATTERNS)
        assert [f.kind for f in findings] == ["missing"], line


def test_audit_accepts_strict_equality_and_typed_ts() -> None:
    clean = "const ok = a !== b;\nconst v: string = name;\n"
    assert audit_text(clean, TS_ANTI_PATTERNS) == []


def test_audit_flags_string_keyed_mapping_with_scalar_value() -> None:
    findings = audit_text("data: Mapping[str, int]\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].rule_id == "dict-str-payload"


def test_audit_accepts_string_keyed_dict_with_concrete_value() -> None:
    # The relaxed rule permits concrete class/callable value types: these are
    # registries/routers whose open, data-driven key set is the point.
    clean = (
        "engines: dict[str, Engine]\n"
        "tools: dict[str, LupMcpTool]\n"
        "factories: Mapping[str, Callable[[], Engine]]\n"
    )
    assert audit_text(clean, PYTHON_ANTI_PATTERNS) == []


def test_audit_accepts_jsonvalue_dicts() -> None:
    clean = "payload: dict[str, JsonValue]\nargs: Mapping[str, JsonValue]\n"
    assert audit_text(clean, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_tuple_variable_and_attribute_annotations() -> None:
    # The rule catches every declared tuple shape, not just return types.
    for line in (
        "pair: tuple[int, str] = (1, 'a')\n",
        "    self.pair: tuple[int, str] = pair\n",
        "def f() -> tuple[int, str]: ...\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert [f.kind for f in findings] == ["missing"], line
        assert findings[0].rule_id == "tuple-shape"


def test_audit_flags_declared_frozenset() -> None:
    for line in (
        "FRAMEWORK_TOOLS: frozenset[str] = frozenset({'x'})\n",
        "TOKENS = frozenset({'a', 'b'})\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert findings and findings[0].rule_id == "frozenset-shape"


def test_audit_flags_bare_set_shape() -> None:
    # A bare `set` is flagged like frozenset; `frozenset` itself trips only
    # frozenset-shape, since its "set" is not a standalone word.
    for line in ("names: set[str]\n", "seen = set(values)\n"):
        rule_ids = {f.rule_id for f in audit_text(line, PYTHON_ANTI_PATTERNS)}
        assert "set-shape" in rule_ids, line
    frozen = audit_text("TOKENS = frozenset({'a'})\n", PYTHON_ANTI_PATTERNS)
    assert [f.rule_id for f in frozen] == ["frozenset-shape"]


def test_audit_flags_empty_collection_literals() -> None:
    for line in ("cache = {}\n", "items = []\n", "buffer = set()\n"):
        rule_ids = {f.rule_id for f in audit_text(line, PYTHON_ANTI_PATTERNS)}
        assert "empty-collection" in rule_ids, line


def test_audit_accepts_populated_and_compared_collections() -> None:
    # Non-empty literals are fine, and a `==` comparison is not an assignment,
    # so the empty-collection rule leaves it alone.
    clean = "cache = {'k': 1}\nitems = [1, 2]\nif payload == {}:\n    pass\n"
    assert audit_text(clean, PYTHON_ANTI_PATTERNS) == []


def test_audit_flags_os_exec_as_shell() -> None:
    for line in ("os.execv(path, args)\n", "os.execvp('ls', argv)\n"):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert findings and findings[0].rule_id == "os-shell", line


def test_audit_flags_both_re_import_forms() -> None:
    for line in ("import re\n", "from re import compile\n"):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert findings and findings[0].rule_id == "import-re", line


def test_audit_flags_os_file_ops_and_environ() -> None:
    for line in (
        "entries = os.listdir(path)\n",
        "os.makedirs(path)\n",
        "os.replace(tmp, dst)\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert findings and findings[0].rule_id == "os-file-ops", line
    for line in (
        "value = os.environ['KEY']\n",
        "home = os.getenv('HOME')\n",
    ):
        findings = audit_text(line, PYTHON_ANTI_PATTERNS)
        assert findings and findings[0].rule_id == "os-environ", line


def test_audit_flags_every_dict_get() -> None:
    findings = audit_text("name = payload.get('name')\n", PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].rule_id == "dict-get"


def test_audit_dict_get_silenced_by_typed_ignore() -> None:
    source = "name = registry.get(key)  # lup: ignore[dict-get]\n"
    assert audit_text(source, PYTHON_ANTI_PATTERNS) == []


def test_audit_file_level_typed_ignore_disables_only_that_rule() -> None:
    # `# lup: ignore[dict-get]` at the top silences dict-get file-wide, but
    # every other rule stays live.
    source = "# lup: ignore[dict-get]\nname = data.get(k)\nx: Any = 1\n"
    findings = audit_text(source, PYTHON_ANTI_PATTERNS)
    assert [f.kind for f in findings] == ["missing"]
    assert findings[0].rule_id == "any-type"
