// The page: every agent the host serves on the left; everything waiting for the
// operator beside it, as one review in groups, one per agent, every agent
// running having one, their reply written into it, their messages to agents
// among it, and a line saying what the reply covers and who it reaches: every
// agent it covers or writes to, each getting all of it. Selecting an agent opens its
// conversation in the review's place; Space `r` in it, the palette, or the
// title bar brings the review back as it was left. Space `h` gives the keyboard
// to the tree, and Space `l` back to the view (`AgentTree.tsx`).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, launches, running, type Agent, type Launch } from "./agents";
import { AgentTree } from "./AgentTree";
import { ask, type Asked, type Replied } from "./api";
import { Conversation } from "./Conversation";
import { Details } from "./Details";
import { useNow, useWatched } from "./hooks";
import { REVIEW_KEYS, REVIEW_PLACES, type ReviewPlace } from "./keys";
import { Keys } from "./Keys";
import { Palette } from "./Palette";
import { Review } from "./Review";
import {
    answer,
    covered,
    EMPTY,
    messages,
    pruned,
    whose,
    type Answered,
    type ChangedFile,
    type Context,
    type Conversation as InboxConversation,
    type Draft,
    type Head,
    type Item,
} from "./review";

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
    // The review's ages are told to the minute, so it's laid out again once a minute, not every second.
    const minute = useNow(60_000);
    const [selected, setSelected] = useState<string | null>(null);
    const [palette, setPalette] = useState(false);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    const [contexts, setContexts] = useState<Map<number, Answered<Context>>>(new Map());
    const [files, setFiles] = useState<Map<number, Answered<ChangedFile[]>>>(new Map());
    const around = useMemo(() => ({ contexts, files }), [contexts, files]);
    // The items whose context, and whose files, were asked for, so each is asked once: an approval's files once
    // more when the judge has read their types (`typing`), each asking keyed by its number and whether they were.
    const asked = useRef({ contexts: new Set<number>(), files: new Set<string>() });
    // Each item's latest asking for its files, whose answer alone is shown.
    const latest = useRef(new Map<number, string>());
    const [said, setSaid] = useState<string | null>(null);
    const [demo, setDemo] = useState(false);
    const [inserting, setInserting] = useState(false);
    // Where the review's cursor is, and whether the list of every key is open: what the line of keys says.
    const [place, setPlace] = useState<Exclude<ReviewPlace, "insert">>("nothing");
    const [listing, setListing] = useState(false);
    const openList = useCallback(() => setListing(true), []);
    const [epoch, setEpoch] = useState(0);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const served = reply?.kind === "listed" ? launches(reply) : [];
    const agents = everyone(served);
    const shown = found(served, agents, selected);
    const talkers = useMemo(() => agents.map((each) => each.talker), [agents]);

    // A party as it's called: a conversation by its path in the tree, else by its runtime's ids.
    const called = useCallback(
        (party: Item["sender"]) => {
            if (party.party === "operator") {
                return "you";
            }
            const talker = talkers.find(
                (each) => each.session === party.session && (each.agent ?? null) === (party.agent ?? null),
            );
            return talker?.path ?? `${party.runtime} ${party.session}${party.agent ? ` / ${party.agent}` : ""}`;
        },
        [talkers],
    );
    const named = useCallback((item: Item) => called(item.sender), [called]);

    // The conversations running, in the tree's order, each with its banner: the review gives each a group.
    const live = useMemo(
        () =>
            running(reply?.kind === "listed" ? launches(reply) : []).map(({ launch, talker }) => {
                const conversation: InboxConversation = {
                    party: "conversation",
                    repository: launch.repository,
                    runtime: launch.runtime,
                    session: talker.session,
                    agent: talker.agent ?? null,
                };
                return { conversation, banner: [last(launch.repository), last(launch.worktree), talker.path].join(" · ") };
            }),
        [reply],
    );
    const agentsRunning = useMemo(() => live.map((each) => each.conversation), [live]);

    const banner = useCallback(
        (head: Head) => {
            if ("conversation" in head) {
                // A conversation that isn't running, written to all the same, by its runtime's ids where it isn't known.
                const key = whose(head.conversation);
                const found = live.find((each) => whose(each.conversation) === key);
                return found?.banner ?? [last(head.conversation.repository), called(head.conversation)].join(" · ");
            }
            const item = head.item;
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
        [named, called, live],
    );

    const waiting = useMemo(() => (inbox.reply?.kind === "inbox-items" ? inbox.reply.items : []), [inbox.reply]);
    const review = useCallback(() => setSelected(null), []);
    const nav = useRef<HTMLElement>(null);
    const main = useRef<HTMLElement>(null);

    // The keyboard to the tree, on the conversation shown, or its first row; and back to the view shown.
    const toTree = useCallback(() => {
        const tree = nav.current;
        const row =
            tree?.querySelector<HTMLElement>('[role="row"][aria-selected="true"]') ??
            tree?.querySelector<HTMLElement>('[role="row"]');
        row?.focus();
    }, []);
    const toView = useCallback(() => {
        const editors = [...(main.current?.querySelectorAll<HTMLElement>(".cm-content") ?? [])];
        editors.find((each) => each.closest("[hidden]") === null)?.focus();
    }, []);

    function hold(agent: Agent) {
        const at = found(served, agents, agent.talker.path);
        if (at === null) {
            return;
        }
        const on = agent.talker.holding !== true;
        const { session, agent: subagent, path } = agent.talker;
        void ask({ kind: "set-holding", launch: at.launch.launch.launch, session, agent: subagent ?? null, on }).then(
            (answer) => {
                if (answer.kind === "refused") {
                    setSaid(answer.error);
                    return;
                }
                setSaid(
                    on
                        ? `Each flagged write of ${path} is held for your answer.`
                        : `${path}'s flagged writes land again, flagged.`,
                );
            },
        );
    }

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

    // The page's build, as the dashboard served it when the page first went live: once the dashboard serves
    // another, as after lup is installed again, the page reloads itself, its drafts being on the host.
    const build = useRef<string | null | undefined>(undefined);
    useEffect(() => {
        if (connection !== "live") {
            return;
        }
        void fetch("/api/about").then(async (response) => {
            if (!response.ok) {
                return;
            }
            const served = ((await response.json()) as { build?: string | null }).build ?? null;
            if (build.current === undefined) {
                build.current = served;
            } else if (served !== null && served !== build.current) {
                window.location.reload();
            }
        });
    }, [connection]);

    const pending = useRef<Draft | null>(null);

    const change = useCallback((next: Draft) => {
        setDraft(next);
        pending.current = next;
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        keeping.current = setTimeout(() => {
            pending.current = null;
            // Refused, as a message to a conversation the host never heard of, it's said; the page keeps it to mend.
            void ask({ kind: "inbox-keep-draft", draft: next }).then((answer) => {
                if (answer.kind === "refused") {
                    setSaid(answer.error);
                }
            });
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
        // Each item's context, where an agent's call made it, and each file an approval or a held change
        // changes, asked once it's in the inbox; an approval's again once the judge has read their types.
        for (const item of waiting) {
            const number = item.number;
            if (item.call != null && !asked.current.contexts.has(number)) {
                asked.current.contexts.add(number);
                void answered({ kind: "inbox-show-context", number }, (answer) =>
                    answer.kind === "inbox-context" ? answer : null,
                ).then((context) => setContexts((before) => new Map(before).set(number, context)));
            }
            const changing = item.reason.reason === "approval" || item.reason.reason === "held";
            const reading = `${number}:${item.reason.reason === "approval" && item.reason.typing}`;
            if (changing && !asked.current.files.has(reading)) {
                asked.current.files.add(reading);
                latest.current.set(number, reading);
                void answered({ kind: "inbox-show-files", number }, (answer) =>
                    answer.kind === "inbox-files" ? answer.files : null,
                ).then((shown) => {
                    // An answer to an earlier asking, arriving after a later one's, is dropped.
                    if (latest.current.get(number) === reading) {
                        setFiles((before) => new Map(before).set(number, shown));
                    }
                });
            }
        }
    }, [waiting]);

    const drafted = useRef(draft);
    drafted.current = draft;

    // An approval or a held change answered, the comments written under it going with the answer, each
    // under what it quotes, and off the draft: a held change's agent reads them with its yes or no, and
    // the session whose push asked an approval reads them as a note.
    const approve = useCallback(
        (number: number, approved: boolean) => {
            const now = drafted.current;
            const comment = answer((now.comments ?? []).filter((each) => each.item === number));
            void ask({ kind: "inbox-answer-approval", number, approved, comment }).then((answer) => {
                if (answer.kind === "refused") {
                    setSaid(answer.error);
                    return;
                }
                setSaid(`#${number} ${approved ? "approved" : "declined"}.`);
                change({ ...now, comments: (now.comments ?? []).filter((each) => each.item !== number) });
            });
        },
        [change],
    );

    async function sent() {
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        // What's sent is what the host keeps: a draft it refuses to keep isn't sent, lest the last one kept go instead.
        const kept = await ask({ kind: "inbox-keep-draft", draft: pruned(draft) });
        if (kept.kind === "refused") {
            setSaid(kept.error);
            return;
        }
        const answer = await ask({ kind: "inbox-send-draft" });
        if (answer.kind === "refused") {
            setSaid(answer.error);
            return;
        }
        if (answer.kind === "inbox-reviewed") {
            const list = (items: { number: number }[]) => items.map((each) => `#${each.number}`).join(", ");
            const approved = answer.approved ?? [];
            const noted = answer.noted ?? [];
            const kept = answer.kept ?? [];
            const done = [
                ...answer.items.map((each) => `#${each.number} to ${called(each.recipient)}`),
                ...(approved.length === 0 ? [] : [`approved ${list(approved)}`]),
                ...noted.map((each) => `comments to ${called(each.recipient)} as #${each.number}`),
                ...(kept.length === 0 ? [] : [`comments on ${kept.map((each) => `#${each}`).join(", ")} kept: no session's push asked it`]),
            ];
            setSaid(`Sent: ${done.join("; ") || "nothing new"}.`);
        }
        const after = await ask({ kind: "inbox-draft" });
        if (after.kind === "inbox-drafted") {
            setDraft(after.draft);
            setEpoch((before) => before + 1);
        }
    }

    const numbers = covered(draft);
    const commented = numbers.filter((number) => (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== ""));
    const coveredItems = waiting.filter((each) => numbers.includes(each.number));
    const yesOrNo = (item: Item) => item.reason.reason === "approval" || item.reason.reason === "held";
    // Approved by the send: an approval or a held change marked read alone, and a held change
    // commented on, its comments going with the yes.
    const approving = coveredItems.filter(
        (each) => yesOrNo(each) && (each.reason.reason === "held" || !commented.includes(each.number)),
    );
    // An approval commented on stays unanswered, its comments going to the session whose push asked it.
    const unanswered = coveredItems.filter((each) => each.reason.reason === "approval" && commented.includes(each.number));
    const pushers = unanswered.flatMap((each) =>
        each.reason.reason === "approval" && each.reason.pushed_by != null ? [called(each.reason.pushed_by)] : [],
    );
    // Told: the agents with a comment on their messages or questions, or a question among them,
    // which an answer lets go; a message only marked read reaches no one.
    const told = coveredItems.filter(
        (each) => !yesOrNo(each) && (commented.includes(each.number) || each.reason.reason === "question"),
    );
    // Written to: each agent a message under its banner is for, which the reply reaches whatever it covers.
    const letters = messages(draft);
    const writtenTo = [...new Set(letters.map((each) => called(each.to)))];
    const reached = [...new Set([...writtenTo, ...told.map(named), ...pushers])];
    const onMessages = commented.filter((number) => told.some((each) => each.number === number));
    const read = coveredItems.filter((each) => !yesOrNo(each) && !commented.includes(each.number)).map((each) => each.number);
    const hashed = (list: number[]) => list.map((each) => `#${each}`).join(", ");
    const replying = numbers.length > 0 || letters.length > 0;
    const covering = [
        ...(writtenTo.length === 0 ? [] : [`${letters.length === 1 ? "a message" : "messages"} to ${writtenTo.join(", ")}`]),
        ...(onMessages.length === 0 ? [] : [`comments on ${hashed(onMessages)}`]),
        ...(read.length === 0 ? [] : [`read ${hashed(read)}`]),
        ...(approving.length === 0 ? [] : [`approving ${hashed(approving.map((each) => each.number))}`]),
        ...(unanswered.length === 0 ? [] : [`comments on ${hashed(unanswered.map((each) => each.number))}, left unanswered`]),
    ];
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
            <nav className="win" aria-label="Agents" ref={nav}>
                <div className="wb">
                    agents <span className="count">{agents.length}</span>
                    <span className="spacer" />
                    <span className="hint">
                        <kbd>h</kbd> hold · <kbd>␣l</kbd> view
                    </span>
                </div>
                <div className="buf">
                    <AgentTree
                        served={served}
                        selected={selected}
                        select={setSelected}
                        now={now}
                        hold={hold}
                        right={toView}
                    />
                </div>
                {shown === null ? null : (
                    <div className="agent-details">
                        <Details launch={shown.launch} agent={shown.agent} now={now} />
                    </div>
                )}
            </nav>
            <main className="win" ref={main}>
                {selected === null ? (
                    <div className="wb">
                        waiting on you <span className="count">{waiting.length}</span>
                    </div>
                ) : shown?.agent == null ? (
                    <>
                        <div className="wb">
                            <button type="button" className="crumb" onClick={review} title="Back to the review">
                                waiting on you <span className="count">{waiting.length}</span>
                            </button>
                            <span className="muted">›</span>
                            <span>{shown === null ? selected : (shown.launch.launch.name ?? shown.launch.launch.launch)}</span>
                        </div>
                        <p className="empty">
                            {shown === null
                                ? "It's no longer served: its launch has ended."
                                : "Its session hasn't started: there's no conversation to read yet."}
                        </p>
                    </>
                ) : (
                    <Conversation
                        key={selected}
                        launch={shown.launch}
                        agent={shown.agent}
                        beat={reply}
                        waiting={waiting.length}
                        back={review}
                        tree={toTree}
                        say={setSaid}
                    />
                )}
                <div className="review" hidden={selected !== null}>
                    <Review
                        items={waiting}
                        agents={agentsRunning}
                        draft={draft}
                        change={change}
                        banner={banner}
                        around={around}
                        send={() => {
                            if (replying) {
                                void sent();
                            }
                        }}
                        approve={approve}
                        inserting={setInserting}
                        epoch={epoch}
                        shown={selected === null}
                        tree={toTree}
                        placed={setPlace}
                        list={openList}
                        reviewed={inbox.reply?.kind === "inbox-items" ? (inbox.reply.reviewed ?? null) : null}
                        now={minute}
                    />
                    <div className="status">
                        {!replying ? (
                            <span className="muted">No reply drafted.</span>
                        ) : (
                            <span>
                                Your reply: {covering.join("; ")}
                                {reached.length === 0
                                    ? ", telling no one"
                                    : ` — to ${reached.join(", ")}${reached.length > 1 ? ", each getting all of it" : ""}`}
                                .{" "}
                                <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends.
                            </span>
                        )}
                        {(draft.parked ?? []).length === 0 ? null : (
                            <span className="muted"> Later: {(draft.parked ?? []).map((each) => `#${each}`).join(", ")}.</span>
                        )}
                    </div>
                    <Keys
                        parts={REVIEW_KEYS}
                        place={inserting ? "insert" : place}
                        places={REVIEW_PLACES}
                        open={listing}
                        setOpen={setListing}
                    />
                </div>
            </main>
            <Palette
                open={palette}
                setOpen={setPalette}
                agents={agents}
                select={setSelected}
                review={review}
                waiting={waiting.length}
                now={now}
            />
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
