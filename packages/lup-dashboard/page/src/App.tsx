// The page: every agent the host serves on the left; everything waiting for the
// operator beside it, as one review in groups, one per agent, their reply
// written into it, and a line saying what the reply covers and who it reaches:
// every agent it covers, each getting all of it. Selecting an agent narrows the
// review to what it and its subagents sent.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, launches, type Agent, type Launch } from "./agents";
import { AgentTree } from "./AgentTree";
import { ask, type Asked, type Replied } from "./api";
import { Details } from "./Details";
import { useNow, useWatched } from "./hooks";
import { Palette } from "./Palette";
import { Review } from "./Review";
import { covered, EMPTY, pruned, type Answered, type Context, type Draft, type Item } from "./review";

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
    const [contexts, setContexts] = useState<Map<number, Answered<Context>>>(new Map());
    const [diffs, setDiffs] = useState<Map<number, Answered<string>>>(new Map());
    const around = useMemo(() => ({ contexts, diffs }), [contexts, diffs]);
    // The items whose context, and whose whole diff, were asked for, so each is asked once.
    const asked = useRef({ contexts: new Set<number>(), diffs: new Set<number>() });
    const [confirming, setConfirming] = useState(false);
    const [said, setSaid] = useState<string | null>(null);
    const [demo, setDemo] = useState(false);
    const [inserting, setInserting] = useState(false);
    const [epoch, setEpoch] = useState(0);
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

    const banner = useCallback(
        (item: Item) => {
            const sender = item.sender;
            const repository =
                sender.party === "conversation"
                    ? sender.repository
                    : item.reason.reason === "approval"
                      ? item.reason.repository
                      : null;
            const where = [repository, item.worktree ?? null].flatMap((each) => (each === null ? [] : [last(each)]));
            return [...where, sender.party === "operator" ? "lup's approvals" : named(item)].join(" · ");
        },
        [named],
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
                setEpoch((before) => before + 1);
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

    useEffect(() => {
        // Each item's context, and an approval's whole diff, asked once it's in the inbox.
        for (const item of waiting) {
            const number = item.number;
            if (!asked.current.contexts.has(number)) {
                asked.current.contexts.add(number);
                void answered({ kind: "inbox-show-context", number }, (answer) =>
                    answer.kind === "inbox-context" ? answer : null,
                ).then((context) => setContexts((before) => new Map(before).set(number, context)));
            }
            if (item.reason.reason === "approval" && !asked.current.diffs.has(number)) {
                asked.current.diffs.add(number);
                void answered({ kind: "inbox-show-diff", number }, (answer) =>
                    answer.kind === "inbox-diff" ? answer.text : null,
                ).then((diff) => setDiffs((before) => new Map(before).set(number, diff)));
            }
        }
    }, [waiting]);

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
            setEpoch((before) => before + 1);
        }
    }

    const numbers = covered(draft);
    const commented = numbers.filter((number) => (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== ""));
    const reached = [...new Set(waiting.filter((each) => numbers.includes(each.number)).map(named))];
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
                        banner={banner}
                        around={around}
                        send={() => setConfirming(numbers.length > 0)}
                        approve={approve}
                        confirming={confirming}
                        inserting={setInserting}
                        epoch={epoch}
                    />
                    <div className="status">
                        {numbers.length === 0 ? (
                            <span className="muted">No reply drafted.</span>
                        ) : (
                            <span>
                                Your reply: {commented.length === 0 ? "" : `comments on ${commented.map((each) => `#${each}`).join(", ")}`}
                                {read.length === 0 ? "" : `${commented.length === 0 ? "" : "; "}read ${read.map((each) => `#${each}`).join(", ")}`}
                                {reached.length === 0 ? "" : ` — to ${reached.join(", ")}${reached.length > 1 ? ", each getting all of it" : ""}`}.{" "}
                                <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends.
                            </span>
                        )}
                        {(draft.parked ?? []).length === 0 ? null : (
                            <span className="muted"> Later: {(draft.parked ?? []).map((each) => `#${each}`).join(", ")}.</span>
                        )}
                    </div>
                    {inserting ? (
                        <div className="keys inserting">
                            -- INSERT -- writing a comment · <kbd>Ctrl</kbd> <kbd>Enter</kbd> ends it, back on what
                            it's about · <kbd>Esc</kbd> ends it here · <kbd>Esc</kbd> <kbd>u</kbd> drops it
                        </div>
                    ) : (
                        <div className="keys muted">
                            comment: <kbd>c</kbd> item · <kbd>o</kbd>/<kbd>C</kbd> line · <kbd>v</kbd>…<kbd>c</kbd>{" "}
                            selection · <kbd>u</kbd>/<kbd>^r</kbd> undo/redo · <kbd>␣d</kbd> read · <kbd>␣z</kbd> later ·{" "}
                            <kbd>␣a</kbd>/<kbd>␣x</kbd> approve/decline · <kbd>za</kbd> fold · <kbd>zR</kbd>/
                            <kbd>zM</kbd> unfold/fold all · <kbd>J</kbd>/<kbd>K</kbd> items
                        </div>
                    )}
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
                    <p>Send your reply to {reached.join(", ")}?</p>
                    <p className="muted">
                        {reached.length === 1
                            ? ""
                            : "Each gets all of it: its own items first, the others' for context. "}
                        <kbd>Enter</kbd> sends · <kbd>Esc</kbd> goes back.
                    </p>
                </div>
            ) : null}
            <Palette open={palette} setOpen={setPalette} agents={agents} select={setSelected} now={now} />
        </div>
    );
}

/** Ask the host for more of an item than its own text: what `shown` takes from its reply, or why it refused, or why it couldn't be asked. */
async function answered<T>(request: Asked, shown: (answer: Replied) => T | null): Promise<Answered<T>> {
    try {
        const answer = await ask(request);
        const taken = shown(answer);
        if (taken !== null) {
            return { shown: taken };
        }
        return { refused: answer.kind === "refused" ? answer.error : `the host answered \`${answer.kind}\`` };
    } catch (error) {
        return { refused: error instanceof Error ? error.message : String(error) };
    }
}

/** Return the last part of a path: a repository's name without its `.git`, a worktree's. */
function last(path: string): string {
    const name = path.split("/").filter((each) => each !== "").at(-1) ?? path;
    return name.endsWith(".git") ? name.slice(0, -".git".length) : name;
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
