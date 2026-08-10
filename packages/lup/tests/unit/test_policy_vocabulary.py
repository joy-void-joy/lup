"""The offered vocabulary decides, and its parameters move exactly one verdict.

A group that shipped nothing was not neutral: an empty table matches no
command, an unmatched command is unjudged, and unjudged resolves to a deny.
The first test pins that the defaults produce a usable agent rather than one
that refuses to list a directory.

The rest pin the parameters. Each exists because a reasonable project answers
differently, so each has to change the verdict it names and leave its
neighbours alone — a parameter that also moved something else would be a fork
wearing an argument's clothes.
"""

from lup.policy.kernel.decision import KernelDecision
from lup.policy.kernel.shell import decide_shell
from lup.policy.shell_rules import ShellCommandRule, erase_shell_rules
from lup.policy.vocabulary import (
    default_vocabulary,
    gh_rule,
    git_rule,
    read_only_rules,
)


def verdict(command: str, rules: list[ShellCommandRule]) -> KernelDecision:
    """Classify one command against a composed vocabulary."""
    return decide_shell(command, erase_shell_rules(rules))


def test_the_offered_defaults_produce_an_agent_that_can_read() -> None:
    """Shipping no vocabulary denied every command, which is not no policy."""
    rules = default_vocabulary()

    assert verdict("ls -la", rules).effect == "allow"
    assert verdict("grep -rn needle src", rules).effect == "allow"
    assert verdict("git status", rules).effect == "allow"
    assert verdict("gh pr list", rules).effect == "allow"
    # Generosity for reads is not generosity for losses.
    assert verdict("rm notes.md", rules).effect == "ask"
    assert verdict("sudo apt install x", rules).effect == "ask"
    # And an empty table is the verdict the library used to ship by default.
    assert verdict("ls -la", []).effect == "deny"


def test_an_empty_group_replaces_the_offered_words_rather_than_adding_to_them() -> None:
    """The words are a parameter default, so passing any replaces all of them."""
    assert verdict("ls", read_only_rules()).effect == "allow"
    assert verdict("ls", read_only_rules(["cat"])).effect == "deny"
    assert verdict("cat f", read_only_rules(["cat"])).effect == "allow"


def test_guard_force_push_moves_only_the_rewriting_push() -> None:
    """A rebase flow republishes every round, so the force is the ordinary case.

    Removing a ref is guarded either way: no second push restores it.
    """
    guarded = [git_rule()]
    open_flow = [git_rule(guard_force_push=False)]

    assert verdict("git push --force origin HEAD", guarded).effect == "ask"
    assert verdict("git push --force origin HEAD", open_flow).effect == "allow"
    assert verdict("git push -f origin HEAD", guarded).effect == "ask"
    assert verdict("git push -f origin HEAD", open_flow).effect == "allow"
    # Neither the plain push nor the removing one moves with the parameter.
    assert verdict("git push -u origin HEAD", guarded).effect == "allow"
    assert verdict("git push -u origin HEAD", open_flow).effect == "allow"
    assert verdict("git push --delete origin old", guarded).effect == "ask"
    assert verdict("git push --delete origin old", open_flow).effect == "ask"


def test_redirect_checkout_chooses_between_asking_and_naming_the_newer_verbs() -> None:
    """Off, checkout asks because `checkout -- <path>` discards work.

    On, it denies and says which verbs replaced it. The ref-sourced form is
    recognized ahead of the row either way, because a named commit still
    holds the content.
    """
    asking = [git_rule()]
    redirecting = [git_rule(redirect_checkout=True)]

    assert verdict("git checkout main", asking).effect == "ask"
    assert verdict("git checkout main", redirecting).effect == "deny"
    assert "git switch" in verdict("git checkout main", redirecting).reason
    assert verdict("git checkout HEAD~1 -- src/x.py", asking).effect == "allow"
    assert verdict("git checkout HEAD~1 -- src/x.py", redirecting).effect == "allow"


def test_allow_authoring_moves_only_the_author_describing_their_own_work() -> None:
    """Opening and titling a PR is authoring; commenting reaches other people."""
    authoring = [gh_rule()]
    publishing = [gh_rule(allow_authoring=False)]

    assert verdict("gh pr create --fill", authoring).effect == "allow"
    assert verdict("gh pr create --fill", publishing).effect == "ask"
    assert verdict("gh pr ready", authoring).effect == "allow"
    assert verdict("gh pr ready", publishing).effect == "ask"
    # Reads and the verbs that reach reviewers stay where they were.
    assert verdict("gh pr view 12", authoring).effect == "allow"
    assert verdict("gh pr view 12", publishing).effect == "allow"
    assert verdict("gh pr merge 12", authoring).effect == "ask"
    assert verdict("gh pr merge 12", publishing).effect == "ask"
