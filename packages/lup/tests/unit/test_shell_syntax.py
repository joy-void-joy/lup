"""The shell grammar reads a line into a tree that keeps quoting and structure.

Each node kind, the quoting each word part records, and the refusals: a line
the grammar will not read comes back as a decision, never as an exception.
"""

import pytest

from lup.policy.kernel.decision import KernelDecision, SUBSTITUTION_SENTINEL
from lup.policy.kernel.syntax import (
    Command,
    Script,
    WordPart,
    parse_script,
    readable_prefix,
    word_text,
)


def tree(source: str) -> Script:
    """The tree a line parses to, failing the test where it does not."""
    parsed = parse_script(source)
    assert not isinstance(parsed, KernelDecision), parsed.reason
    return parsed


def refusal(source: str) -> KernelDecision:
    """The decision a line the grammar refuses comes back as."""
    parsed = parse_script(source)
    assert isinstance(parsed, KernelDecision), source
    return parsed


def only(source: str) -> Command:
    """The single command a one-command line holds."""
    items = tree(source)["items"]
    assert len(items) == 1
    pipelines = items[0]["andor"]["pipelines"]
    assert len(pipelines) == 1 and len(pipelines[0]["commands"]) == 1
    return pipelines[0]["commands"][0]


def parts(source: str, index: int = 1) -> list[WordPart]:
    """The parts of one word of a one-command line."""
    return only(source)["words"][index]["parts"]


def test_a_list_keeps_its_terminators_and_and_or_structure() -> None:
    """`;`, `&`, `&&`, `||` and newlines are each where the line put them."""
    script = tree("a && b || c; d &\ne")
    assert [item["terminator"] for item in script["items"]] == [";", "&", ""]
    assert script["items"][0]["andor"]["operators"] == ["&&", "||"]
    assert len(script["items"][0]["andor"]["pipelines"]) == 3


def test_a_pipeline_keeps_its_operators_and_negation() -> None:
    """`!` negates the pipeline and `|&` is told from `|`."""
    pipeline = tree("! a | b |& c")["items"][0]["andor"]["pipelines"][0]
    assert pipeline["negated"]
    assert pipeline["operators"] == ["|", "|&"]
    assert [word_text(command["words"][0]) for command in pipeline["commands"]] == [
        "a",
        "b",
        "c",
    ]


def test_a_simple_command_carries_its_redirections_apart_from_its_words() -> None:
    """Descriptors, appends, duplications and here-strings are each an operator."""
    command = only("cmd arg 2>err.log >> out <<< text 2>&1 >| forced")
    assert [word_text(word) for word in command["words"]] == ["cmd", "arg"]
    assert [
        (redirect["operator"], [word_text(word) for word in redirect["target"]])
        for redirect in command["redirects"]
    ] == [
        ("2>", ["err.log"]),
        (">>", ["out"]),
        ("<<<", ["text"]),
        ("2>&1", []),
        (">|", ["forced"]),
    ]


@pytest.mark.parametrize(
    ("source", "kind"),
    [
        ("{ a; b; }", "brace"),
        ("( a; b )", "subshell"),
        ("if a; then b; elif c; then d; else e; fi", "if"),
        ("for x in 1 2; do a; done", "for"),
        ("select x in 1 2; do a; done", "select"),
        ("while a; do b; done", "while"),
        ("until a; do b; done", "until"),
        ("case $x in a|b) c;; (d) e;& *) f;;& esac", "case"),
        ("f () { a; }", "function"),
        ("function f { a; }", "function"),
        ("(( i = 1 ))", "arithmetic"),
        ("[[ -f a && $b == c ]]", "test"),
    ],
)
def test_every_compound_command_is_its_own_node(source: str, kind: str) -> None:
    """Structure is read off the grammar, not off keywords in front of segments."""
    assert only(source)["kind"] == kind


def test_a_conditional_keeps_each_clause_and_its_else() -> None:
    """Two clauses and an `else` body, each list in its place."""
    command = only("if a; then b; elif c; then d; else e; fi")
    assert len(command["clauses"]) == 2
    assert len(command["body"]["items"]) == 1


def test_a_loop_keeps_its_name_its_list_and_whether_it_has_one() -> None:
    """`for x; do` iterates the positional parameters, which is not a list."""
    listed = only("for x in 'a b' c; do echo $x; done")
    assert listed["name"] == "x"
    assert listed["listed"]
    assert [word_text(word) for word in listed["words"]] == ["a b", "c"]
    assert not only("for x; do echo; done")["listed"]


def test_a_case_keeps_each_arm_s_patterns() -> None:
    """Alternation and the optional opening parenthesis both read as patterns."""
    command = only("case $x in a|b) c;; (d) e;; esac")
    assert [
        [word_text(pattern) for pattern in arm["patterns"]] for arm in command["arms"]
    ] == [["a", "b"], ["d"]]


def test_a_compound_command_carries_its_own_redirections() -> None:
    """`done < file` belongs to the loop, not to the last command inside it."""
    command = only("while read -r l; do echo $l; done < input")
    assert [redirect["operator"] for redirect in command["redirects"]] == ["<"]


def test_single_quotes_keep_a_dollar_sign_literal() -> None:
    """`'$S'` is two characters, not a parameter."""
    assert [item["kind"] for item in parts("echo '$S'")] == ["single"]
    assert word_text(only("echo '$S'")["words"][1]) == "$S"


def test_double_quotes_keep_the_expansions_inside_them() -> None:
    """`"a $S b"` holds a live parameter between two literals."""
    (quoted,) = parts('echo "a $S b"')
    assert quoted["kind"] == "double"
    assert [child["kind"] for child in quoted["parts"]] == [
        "literal",
        "param",
        "literal",
    ]


def test_a_backslash_in_double_quotes_escapes_only_what_posix_says() -> None:
    """`"a\\n"` keeps its backslash, which is what printf is handed."""
    assert word_text(only('printf "a\\n"')["words"][1]) == "a\\n"
    assert word_text(only('echo "a\\$b"')["words"][1]) == "a$b"


def test_every_parameter_form_names_its_parameter_and_operator() -> None:
    """Plain, braced, defaulting, length and special parameters."""
    spelled = {
        source: (parts(source)[0]["name"], parts(source)[0]["operator"])
        for source in ("echo $X", "echo ${X}", "echo ${X:=d}", "echo ${#X}", "echo $1")
    }
    assert spelled == {
        "echo $X": ("X", ""),
        "echo ${X}": ("X", ""),
        "echo ${X:=d}": ("X", ":="),
        "echo ${#X}": ("X", "length"),
        "echo $1": ("1", ""),
    }


def test_a_substitution_inside_a_parameter_operand_is_parsed() -> None:
    """`${X:-$(cmd)}` runs `cmd`, so the tree holds it."""
    (parameter,) = parts("echo ${X:-$(date)}")
    (substitution,) = parameter["parts"]
    assert substitution["kind"] == "command"
    assert substitution["script"][0]["items"]


def test_substitutions_hold_the_command_they_run() -> None:
    """`$(…)` and `<(…)` each carry a parsed script."""
    (command,) = parts("echo $(git status)")
    assert command["kind"] == "command"
    assert word_text(only("echo $(git status)")["words"][1]) == SUBSTITUTION_SENTINEL
    (process,) = parts("diff <(ls a) b")
    assert process["kind"] == "process"
    assert word_text(only("diff <(ls a) b")["words"][1]) == "/dev/fd/63"


def test_arithmetic_globs_and_tildes_are_their_own_parts() -> None:
    """Each expands in its own way, so each is marked."""
    assert [item["kind"] for item in parts("echo $((1 + 2))")] == ["arithmetic"]
    assert [item["kind"] for item in parts("ls *.py")] == ["glob", "literal"]
    assert [item["kind"] for item in parts("ls ~/src")] == ["tilde", "literal"]
    assert [item["kind"] for item in parts("ls '*.py'")] == ["single"]


def test_a_heredoc_records_its_quoting_and_body() -> None:
    """A quoted delimiter makes the body literal; the body is kept either way."""
    command = only("cat > f <<'EOF'\nhi $P\nEOF")
    heredoc = next(
        redirect["heredoc"][0]
        for redirect in command["redirects"]
        if redirect["heredoc"]
    )
    assert heredoc == {"delimiter": "EOF", "quoted": True, "body": "hi $P\n"}
    unquoted = only("cat <<EOF\nhi\nEOF")["redirects"][0]["heredoc"][0]
    assert not unquoted["quoted"]


@pytest.mark.parametrize(
    ("source", "effect"),
    [
        ("echo 'unterminated", "defer"),
        ('echo "unterminated', "defer"),
        ("echo $(unclosed", "defer"),
        ("if a; then b", "defer"),
        ("for x in a; do b", "defer"),
        ("case a in b) c", "defer"),
        ("a ;; b", "defer"),
        (") a", "defer"),
        ("cat <<EOF\nno end", "defer"),
        ("cat <<", "defer"),
        ("a=(1 2)", "defer"),
        ("echo $($($(ls)))", "defer"),
        ("echo `ls`", "deny"),
        ("cat <<EOF\n$(date)\nEOF", "deny"),
        ("echo $(( $(ls) ))", "deny"),
        ("tee >(cat)", "ask"),
        (") `ls`", "deny"),
        ("((((((((((" * 20, "defer"),
    ],
)
def test_a_malformed_line_is_a_decision_never_an_exception(
    source: str, effect: str
) -> None:
    """Every refusal is returned, and a later lexical refusal outranks abstaining."""
    assert refusal(source).effect == effect


def test_the_lines_before_a_refused_one_are_still_readable() -> None:
    """The shell ran them before it met the line that does not parse."""
    prefix = readable_prefix("rm -rf build\nls; )\necho never")
    assert [
        word_text(item["andor"]["pipelines"][0]["commands"][0]["words"][0])
        for item in prefix["items"]
    ] == ["rm"]
    assert readable_prefix("ls; )")["items"] == []
