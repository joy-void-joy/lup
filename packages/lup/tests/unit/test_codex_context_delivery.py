"""Actor mail reaches a native turn before its durable receipt advances."""

import asyncio
from pathlib import Path

import pytest

from lup.coordination.mail import ActorMail
from lup.coordination.refs import ActorRef
from lup.coordination.sessions import ActorInbox, create_inbox_hooks
from lup.providers.codex.hooks import COMMAND_APPROVAL, CodexApprovalResponder
from lup.resolver.journal import Journal
from lup.policy.hooks import LupHookInput, LupHookMatcher, LupHookOutput, LupHooksConfig


@pytest.fixture
def inbox(tmp_path: Path) -> ActorInbox:
    actor = ActorRef(kind="worker", id="delivery")
    return ActorInbox(ActorMail(tmp_path), Journal(tmp_path), actor)


@pytest.mark.parametrize("redirect", [False, True])
async def test_a_native_receipt_delivers_each_kind_of_actor_mail_once(
    inbox: ActorInbox, redirect: bool
) -> None:
    inbox.mail.send(inbox.actor, "use the repaired tree", redirect=redirect)
    delivered: list[str] = []

    async def receive(text: str) -> None:
        assert len(inbox.waiting().messages) == 1
        delivered.append(text)

    responder = CodexApprovalResponder(
        hooks=create_inbox_hooks(inbox), deliver_context=receive
    )
    decision = await responder.decide(COMMAND_APPROVAL, {"command": "git status"})
    assert decision == "decline"  # Inbox delivery never grants an approval.
    assert len(delivered) == 1
    assert "use the repaired tree" in delivered[0]
    assert inbox.waiting().messages == []
    await responder.deliver_pending()
    assert len(delivered) == 1


async def test_context_without_a_native_transport_stays_pending(
    inbox: ActorInbox,
) -> None:
    inbox.mail.send(inbox.actor, "still needed")
    responder = CodexApprovalResponder(hooks=create_inbox_hooks(inbox))
    decision = await responder.decide(COMMAND_APPROVAL, {"command": "git status"})
    assert decision == "decline"
    assert [message.text for message in inbox.waiting().messages] == ["still needed"]
    assert not Journal(inbox.mail.root).read()


async def test_a_rejected_native_delivery_leaves_no_false_receipt(
    inbox: ActorInbox,
) -> None:
    inbox.mail.send(inbox.actor, "retry this delivery")

    async def refused(_text: str) -> None:
        raise RuntimeError("turn already completed")

    responder = CodexApprovalResponder(
        hooks=create_inbox_hooks(inbox), deliver_context=refused
    )
    decision = await responder.decide(COMMAND_APPROVAL, {"command": "git status"})
    assert decision == "decline"
    assert len(inbox.waiting().messages) == 1
    assert not Journal(inbox.mail.root).read()


async def test_activity_that_needs_no_approval_still_delivers_mail(
    inbox: ActorInbox,
) -> None:
    inbox.mail.send(inbox.actor, "late review evidence")
    received: list[str] = []

    async def receive(text: str) -> None:
        received.append(text)

    responder = CodexApprovalResponder(
        hooks=create_inbox_hooks(inbox), deliver_context=receive
    )
    await responder.deliver_pending()
    assert len(received) == 1
    assert "late review evidence" in received[0]
    assert inbox.waiting().messages == []


async def test_an_approval_and_activity_share_one_delivery(
    inbox: ActorInbox,
) -> None:
    inbox.mail.send(inbox.actor, "one delivery")
    entered = asyncio.Event()
    release = asyncio.Event()
    received: list[str] = []

    async def receive(text: str) -> None:
        received.append(text)
        entered.set()
        await release.wait()

    responder = CodexApprovalResponder(
        hooks=create_inbox_hooks(inbox), deliver_context=receive
    )
    approval = asyncio.create_task(
        responder.decide(COMMAND_APPROVAL, {"command": "git status"})
    )
    await entered.wait()
    activity = asyncio.create_task(responder.deliver_pending())
    release.set()
    await asyncio.gather(approval, activity)
    assert len(received) == 1
    assert inbox.waiting().messages == []


async def test_canceling_delivery_keeps_mail_for_the_next_turn(
    inbox: ActorInbox,
) -> None:
    inbox.mail.send(inbox.actor, "survive cancellation")
    entered = asyncio.Event()
    suspended = asyncio.Event()

    async def receive(_text: str) -> None:
        entered.set()
        await suspended.wait()

    responder = CodexApprovalResponder(
        hooks=create_inbox_hooks(inbox), deliver_context=receive
    )
    pending = asyncio.create_task(responder.deliver_pending())
    await entered.wait()
    pending.cancel()
    with pytest.raises(asyncio.CancelledError):
        await pending
    assert len(inbox.waiting().messages) == 1
    assert not Journal(inbox.mail.root).read()


@pytest.mark.parametrize("matcher", [None, "", "*", "^item/commandExecution/"])
async def test_approval_callbacks_honor_native_method_matchers(
    matcher: str | None,
) -> None:
    calls: list[str] = []

    async def allowed(event: LupHookInput) -> LupHookOutput:
        calls.append(event.tool_name)
        return LupHookOutput(decision="allow")

    async def unrelated(_event: LupHookInput) -> LupHookOutput:
        raise AssertionError("an unrelated tool matcher must not run")

    responder = CodexApprovalResponder(
        hooks=LupHooksConfig(
            pre_tool_use=[
                LupHookMatcher(matcher=matcher, hook=allowed),
                LupHookMatcher(matcher="^different$", hook=unrelated),
            ]
        )
    )
    assert await responder.decide(COMMAND_APPROVAL, {}) == "accept"
    assert calls == [COMMAND_APPROVAL]


async def test_unmatched_approval_declines() -> None:
    async def unrelated(_event: LupHookInput) -> LupHookOutput:
        raise AssertionError("must not run")

    responder = CodexApprovalResponder(
        hooks=LupHooksConfig(
            pre_tool_use=[
                LupHookMatcher(matcher="^different$", hook=unrelated),
            ]
        )
    )
    assert await responder.decide(COMMAND_APPROVAL, {}) == "decline"


async def test_a_rewrite_never_approves_the_original_command() -> None:
    async def rewritten(_event: LupHookInput) -> LupHookOutput:
        return LupHookOutput(decision="allow", updated_input={"command": "safe"})

    received: list[str] = []

    async def receive(text: str) -> None:
        received.append(text)

    responder = CodexApprovalResponder(
        hooks=LupHooksConfig(pre_tool_use=[LupHookMatcher(hook=rewritten)]),
        deliver_context=receive,
    )
    assert await responder.decide(COMMAND_APPROVAL, {"command": "unsafe"}) == "decline"
    assert "cannot rewrite tool input" in received[0]


def test_receipt_is_private_to_adapter_transport() -> None:
    output = LupHookOutput(delivery_receipt=lambda: None)
    assert "delivery_receipt" not in output.model_dump()
    assert "delivery_receipt" not in LupHookOutput.model_json_schema()["properties"]
