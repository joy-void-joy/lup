// The page: every agent the host serves on the left; everything waiting for the
// operator beside it, as one review, their reply written into it, and a line
// saying what the reply covers and who it reaches. Selecting an agent narrows the
// review to what it and its subagents sent.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, launches, type Agent, type Launch } from "./agents";
import { AgentTree } from "./AgentTree";
import { ask } from "./api";
import { Details } from "./Details";
import { useNow, useWatched } from "./hooks";
import { Palette } from "./Palette";
import { Review } from "./Review";
import { covered, EMPTY, pruned, type Draft, type Item } from "./review";

const SAID = {
    connecting: "connecting",
    live: "live",
    retrying: "out of reach, trying again",
    refused: "this page's token is refused: open the dashboard again from `lup-dev dashboard`",
};

export function App() {
    const { reply, connection } = useWatched({ kind: "list" });
    const inbox = useWatched({ kind: "inbox-list" });
    const now = useNow();
    const [selected, setSelected] = useState<string | null>(null);
    const [palette, setPalette] = useState(false);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    const [diffs, setDiffs] = useState<Map<number, string>>(new Map());
    const [confirming, setConfirming] = useState(false);
    const [said, setSaid] = useState<string | null>(null);
    const [demo, setDemo] = useState(false);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const served = reply?.kind === "listed" ? launches(reply) : [];
    const agents = everyone(served);
    const shown = found(served, agents, selected);
    const talkers = useMemo(() => agents.map((each) => each.talker), [agents]);

    const named = useCallback(
        (item: Item) => {
            const sender = item.sender;
            if (sender.party === "operator") {
                return "you";
            }
            const talker = talkers.find(
                (each) => each.session === sender.session && (each.agent ?? null) === (sender.agent ?? null),
            );
            return talker?.path ?? `${sender.runtime} ${sender.session}${sender.agent ? ` / ${sender.agent}` : ""}`;
        },
        [talkers],
    );

    const waiting = useMemo(() => (inbox.reply?.kind === "inbox-items" ? inbox.reply.items : []), [inbox.reply]);
    const items = useMemo(
        () =>
            selected === null
                ? waiting
                : waiting.filter((each) => {
                      const path = named(each);
                      return path === selected || path.startsWith(`${selected}/`);
                  }),
        [waiting, selected, named],
    );

    useEffect(() => {
        void ask({ kind: "inbox-draft" }).then((answer) => {
            if (answer.kind === "inbox-drafted") {
                setDraft(answer.draft);
            }
        });
        void fetch("/api/about").then(async (response) => {
            if (response.ok) {
                setDemo(((await response.json()) as { demo: boolean }).demo);
            }
        });
    }, []);

    const pending = useRef<Draft | null>(null);

    const change = useCallback((next: Draft) => {
        setDraft(next);
        pending.current = next;
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        keeping.current = setTimeout(() => {
            pending.current = null;
            void ask({ kind: "inbox-keep-draft", draft: next });
        }, 300);
    }, []);

    useEffect(() => {
        // A comment written just before the page closes is kept all the same.
        const flush = () => {
            if (pending.current !== null) {
                void fetch("/api/ask", {
                    method: "POST",
                    headers: { "Content-Type": "application/json" },
                    body: JSON.stringify({ kind: "inbox-keep-draft", draft: pending.current }),
                    keepalive: true,
                });
            }
        };
        window.addEventListener("pagehide", flush);
        return () => window.removeEventListener("pagehide", flush);
    }, []);

    const open = useCallback((number: number) => {
        void ask({ kind: "inbox-show-diff", number }).then((answer) => {
            if (answer.kind === "inbox-diff") {
                setDiffs((before) => new Map(before).set(number, answer.text));
            }
        });
    }, []);

    const approve = useCallback((number: number, approved: boolean) => {
        void ask({ kind: "inbox-answer-approval", number, approved }).then((answer) => {
            setSaid(answer.kind === "refused" ? answer.error : `#${number} ${approved ? "approved" : "declined"}.`);
        });
    }, []);

    async function sent() {
        setConfirming(false);
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        await ask({ kind: "inbox-keep-draft", draft: pruned(draft) });
        const answer = await ask({ kind: "inbox-send-draft" });
        if (answer.kind === "refused") {
            setSaid(answer.error);
            return;
        }
        if (answer.kind === "inbox-reviewed") {
            setSaid(`Sent: ${answer.items.map((each) => `#${each.number} to ${named(each)}`).join(", ") || "nothing new"}.`);
        }
        const after = await ask({ kind: "inbox-draft" });
        if (after.kind === "inbox-drafted") {
            setDraft(after.draft);
        }
    }

    const numbers = covered(draft);
    const commented = numbers.filter((number) => (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== ""));
    const reached = [
        ...new Set(waiting.filter((each) => commented.includes(each.number) || (each.reason.reason === "question" && numbers.includes(each.number))).map(named)),
    ];
    const read = numbers.filter((number) => !commented.includes(number));
    return (
        <div className="layout">
            <header className="bar">
                <span className="name">lup</span>
                {demo ? <span className="demo">demo · stand-in data, nothing reaches an agent</span> : null}
                <span className="connection" data-state={connection}>
                    {SAID[connection]}
                </span>
                {reply?.kind === "refused" ? <span className="error">{reply.error}</span> : null}
                {said === null ? null : <span className="said">{said}</span>}
                <span className="spacer" />
                <button type="button" onClick={() => setPalette(true)}>
                    Go to <kbd>Ctrl</kbd> <kbd>K</kbd>
                </button>
            </header>
            <nav className="win" aria-label="Agents">
                <div className="wb">
                    agents <span className="count">{agents.length}</span>
                </div>
                <div className="buf">
                    <AgentTree served={served} selected={selected} select={setSelected} now={now} />
                </div>
                {shown === null ? null : (
                    <div className="agent-details">
                        <Details launch={shown.launch} agent={shown.agent} now={now} />
                    </div>
                )}
            </nav>
            <main className="win">
                <div className="wb">
                    waiting on you <span className="count">{items.length}</span>
                    {selected === null ? null : (
                        <button type="button" className="all" onClick={() => setSelected(null)}>
                            from {selected} · show all
                        </button>
                    )}
                </div>
                <div className="review">
                    <Review
                        items={items}
                        draft={draft}
                        change={change}
                        name={named}
                        diffs={diffs}
                        open={open}
                        send={() => setConfirming(numbers.length > 0)}
                        approve={approve}
                    />
                    <div className="status">
                        {numbers.length === 0 ? (
                            <span className="muted">No reply drafted.</span>
                        ) : (
                            <span>
                                Your reply: {commented.length === 0 ? "" : `comments on ${commented.map((each) => `#${each}`).join(", ")}`}
                                {read.length === 0 ? "" : `${commented.length === 0 ? "" : "; "}read ${read.map((each) => `#${each}`).join(", ")}`}
                                {reached.length === 0 ? "" : `, to ${reached.join(", ")}`}. <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends.
                            </span>
                        )}
                        {(draft.parked ?? []).length === 0 ? null : (
                            <span className="muted"> Later: {(draft.parked ?? []).map((each) => `#${each}`).join(", ")}.</span>
                        )}
                    </div>
                    <div className="keys muted">
                        <kbd>o</kbd> comment on this line (the header: the item) · <kbd>v</kbd>…<kbd>c</kbd> on the
                        selection · <kbd>␣</kbd> <kbd>d</kbd> done · <kbd>␣</kbd> <kbd>z</kbd> later · <kbd>␣</kbd>{" "}
                        <kbd>e</kbd> diff · <kbd>␣</kbd> <kbd>a</kbd>/<kbd>x</kbd> approve/decline · <kbd>J</kbd>/
                        <kbd>K</kbd> items
                    </div>
                </div>
            </main>
            {confirming ? (
                <div
                    className="confirm"
                    role="dialog"
                    aria-label="Send your reply"
                    tabIndex={-1}
                    ref={(box) => box?.focus()}
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            void sent();
                        }
                        if (event.key === "Escape") {
                            setConfirming(false);
                        }
                    }}
                >
                    <p>
                        {reached.length === 0
                            ? `Take ${read.map((each) => `#${each}`).join(", ")} off your list, telling no one?`
                            : `Send your comments to ${reached.join(", ")}?`}
                    </p>
                    <p className="muted">
                        Each gets only what's on its own items. <kbd>Enter</kbd> sends · <kbd>Esc</kbd> goes back.
                    </p>
                </div>
            ) : null}
            <Palette open={palette} setOpen={setPalette} agents={agents} select={setSelected} now={now} />
        </div>
    );
}

/** The launch and conversation `key` names: a conversation's path, or a launch whose session hasn't started. */
function found(
    served: Launch[],
    agents: Agent[],
    key: string | null,
): { launch: Launch; agent: Agent | null } | null {
    if (key === null) {
        return null;
    }
    const waiting = served.find((each) => `launch:${each.launch.launch}` === key);
    if (waiting !== undefined) {
        return { launch: waiting, agent: null };
    }
    const agent = agents.find((each) => each.talker.path === key);
    const launch = served.find((each) => agent !== undefined && each.session !== null && within(each.session, agent));
    return agent === undefined || launch === undefined ? null : { launch, agent };
}

function within(root: Agent, agent: Agent): boolean {
    return root === agent || root.children.some((child) => within(child, agent));
}
