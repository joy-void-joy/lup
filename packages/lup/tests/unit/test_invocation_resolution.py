"""An invocation the plugin cannot answer is refused, all of them at once, by where.

The failure these pin is the one an adopter meets declining a module: every
pointer into it is left naming a skill nobody ships. Refusing only the first,
by the skill's name alone, turned that into one failed build per pointer, each
leaving its reader to find the declaration holding it. So the refusal names
every one, with the declaration a project would change and the passage whose
words hold it — and a pointer the reading module can do without is written so
it holds only where its skill ships.
"""

from pathlib import Path

import pytest
from pydantic import ValidationError

import lup.harness.models as models
from lup.devtools.harness.generate import ProjectContent, installer_guidance
from lup.providers.harness import claude_prompt_renderer

PASSAGE = "lup.harness.content.docs.contributing"
"""A module whose `resolve-pass` passage places exactly one invocation."""


def skill(name: str, *parts: models.PromptPart) -> models.Skill:
    """One skill whose prompt is the given parts, or one line of prose."""
    return models.Skill(
        id=f"skill.{name}",
        name=name,
        description="A worked-example skill.",
        prompt=models.PromptDocument(
            source=__name__, parts=list(parts) or [models.TextPart(text="Do it.")]
        ),
    )


def harness(
    skills: list[models.Skill],
    agents: list[models.Agent] | None = None,
    sections: list[models.GuidanceSection] | None = None,
) -> models.Harness:
    """A one-plugin harness shipping exactly these declarations."""
    return models.Harness(
        generator_version="0",
        plugins=[
            models.Plugin(
                id="plugin.lup",
                name="lup",
                marketplace="worked-example",
                version="0",
                description="A worked-example plugin.",
                skills=skills,
                agents=agents or [],
            )
        ],
        guidance=models.GuidanceDocument(source=__name__, sections=sections or []),
    )


def gone(name: str) -> models.SkillInvocation:
    """An invocation of a skill no harness here ships."""
    return models.SkillInvocation(plugin="lup", skill=name)


def pointer_to(name: str) -> models.WhereShipped:
    """Words that hold only where the named skill ships."""
    return models.WhereShipped(
        parts=[models.TextPart(text=" See `"), gone(name), models.TextPart(text="`.")]
    )


def test_every_unresolvable_invocation_is_named_with_the_declaration_holding_it() -> (
    None
):
    """One refusal for all of them, each saying where a reader goes to fix it.

    A guidance section by its id, a skill or an agent by its name, and the
    passage whose words place the invocation where one does — which is what
    the flattened document the runtimes load could never say.
    """
    kept = skill("kept", models.TextPart(text="First "), gone("commit"))
    helper = models.Agent(
        id="agent.helper",
        name="helper",
        description="A worked-example agent.",
        prompt=models.PromptDocument(source=__name__, parts=[gone("merge")]),
    )
    pointers = models.GuidanceSection(
        id="pointers",
        chapter="gates",
        parts=[
            models.Passage(
                module=PASSAGE,
                name="resolve-pass",
                values={"resolve_skill": gone("resolve")},
            )
        ],
    )

    with pytest.raises(ValidationError) as refused:
        harness([kept], [helper], [pointers])

    report = str(refused.value)
    assert "3 skill invocation(s) cannot be resolved" in report
    assert (
        "lup:resolve names no skill this harness ships, in guidance section "
        f"'pointers' (the 'resolve-pass' passage of {PASSAGE})"
    ) in report
    assert "lup:commit names no skill this harness ships, in skill 'kept'" in report
    assert "lup:merge names no skill this harness ships, in agent 'helper'" in report
    assert "`requires`" in report and "`WhereShipped`" in report


def test_a_wrong_argument_is_reported_beside_a_missing_skill() -> None:
    """Every fault an invocation can have answers in the same list."""
    target = skill("target")
    caller = skill(
        "caller",
        models.SkillInvocation(
            plugin="lup",
            skill="target",
            arguments=[models.InvocationArgument(name="nope", value="x")],
        ),
        gone("absent"),
    )

    with pytest.raises(ValidationError) as refused:
        harness([target, caller])

    report = str(refused.value)
    assert "lup:target has an unknown argument, in skill 'caller'" in report
    assert "lup:absent names no skill this harness ships, in skill 'caller'" in report


def test_a_pointer_holds_exactly_where_its_skill_ships() -> None:
    """Settled against a roster, the words stay or go, and nothing else moves.

    Withheld words keep their seat and say nothing: no walk reaches them and
    no renderer spells them, so neither the invocation nor its prose survives.
    """
    held = pointer_to("merge")
    sentence = models.Passage(
        module=PASSAGE, name="resolve-pass", values={"resolve_skill": held}
    )
    withheld = held.shipped([skill("commit")])
    renderer = claude_prompt_renderer()

    assert held.shipped([skill("merge")]) == held
    assert withheld.held is False
    assert withheld.issued() == [] and withheld.reached() == [withheld]
    assert renderer.render(models.PromptDocument(parts=[withheld])).strip() == ""
    assert sentence.shipped([]).values["resolve_skill"] == withheld


def test_a_settled_pointer_passes_and_an_unsettled_one_is_refused() -> None:
    """Left unsettled it spells its words, so the harness refuses it like any other.

    That is what keeps a composition that forgot to settle one from shipping
    a pointer to nothing: the part's default is the strict reading.
    """
    words = [models.TextPart(text="Commit.")]
    settled = skill("kept", *words, pointer_to("merge").shipped([skill("kept")]))

    assert harness([settled]).plugins[0].skills == [settled]
    with pytest.raises(ValidationError, match="lup:merge names no skill"):
        harness([skill("kept", *words, pointer_to("merge"))])


def test_a_pointer_must_invoke_what_decides_it_and_carry_nothing_else() -> None:
    """Words invoking nothing would always hold; arguments would leave with it."""
    with pytest.raises(ValidationError, match="invoke no skill"):
        models.WhereShipped(parts=[models.TextPart(text="nothing decides this")])
    with pytest.raises(ValidationError, match="own arguments"):
        models.WhereShipped(parts=[gone("merge"), models.ArgumentsRef()])


def test_a_page_is_held_to_the_plugin_it_is_published_beside() -> None:
    """A page composes beside the harness, so it is asked the same question."""
    page = models.Document(
        path=Path("docs/worked.md"),
        semantic_id="docs.worked",
        source="worked_example/docs/worked.py",
        document=models.PromptDocument(source=__name__, parts=[gone("resolve")]),
    )

    with pytest.raises(ValidationError) as refused:
        ProjectContent(harness=harness([skill("kept")]), documents=[page])

    assert "lup:resolve names no skill this harness ships, in page 'docs.worked'" in (
        str(refused.value)
    )


def test_installer_guidance_reads_as_the_plugin_it_installs_ships() -> None:
    """A pointer to a skill the plugin lacks goes; a bare invocation is refused."""
    shipped = harness([skill("kept")])
    guidance = models.PromptDocument(
        source=__name__,
        parts=[models.TextPart(text="Install it."), pointer_to("resolve")],
    )

    [artifact] = installer_guidance(
        path=Path("TEMPLATE.md"),
        document=guidance,
        prompts=claude_prompt_renderer(),
        source=shipped,
    )

    assert "resolve" not in artifact.content
    with pytest.raises(ValueError, match="in installer guidance"):
        installer_guidance(
            path=Path("TEMPLATE.md"),
            document=models.PromptDocument(source=__name__, parts=[gone("resolve")]),
            prompts=claude_prompt_renderer(),
            source=shipped,
        )


def test_a_page_passage_spelling_an_invocation_is_refused(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Spelled as text, an invocation escapes the check that would catch it.

    It names a skill in one runtime's sigil and stays in the page when the
    module shipping the skill is declined, so a page places a SkillInvocation
    value instead — which is what this passage does, and why it passes, while
    the same words spelled literally do not.
    """
    placed = models.Document(
        path=Path("docs/worked.md"),
        semantic_id="docs.worked",
        source="worked_example/docs/worked.py",
        document=models.PromptDocument(
            source=__name__,
            parts=[
                models.Passage(
                    module=PASSAGE,
                    name="resolve-pass",
                    values={"resolve_skill": gone("resolve")},
                )
            ],
        ),
    )
    (tmp_path / "spelled_page_example.py").write_text("")
    (tmp_path / "spelled_page_example.passage.md").write_text(
        "Resolve a conflict with `/lup:merge`.\n"
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    shipped = harness([skill("resolve")])

    assert ProjectContent(harness=shipped, documents=[placed]).documents == [placed]
    with pytest.raises(ValidationError, match="spell an invocation as text"):
        ProjectContent(
            harness=shipped,
            documents=[
                placed.model_copy(
                    update={
                        "document": models.PromptDocument(
                            source=__name__,
                            parts=[
                                models.Passage(module="spelled_page_example", values={})
                            ],
                        )
                    }
                )
            ],
        )
