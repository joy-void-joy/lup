// The page: everything waiting for the operator as one review in groups, one
// per agent, every agent running having one, its banner saying what the agent
// is doing, what it's working on and its context, its drawers at the group's end
// holding its tasks, its trace, what its branch changed since the operator
// approved it and its whole conversation; the operator's reply written into it,
// their messages to agents and their remarks in the drawers among it, and a line
// saying what the reply covers and who it reaches: every agent it covers or
// writes to, each getting all of it. The palette (Ctrl+K) goes to an agent's
// group. Each agent's record is read at every hook the host hears and every
// five seconds besides, for its banner and its drawers; what its branch changed
// since the operator approved it every ten seconds, with the version shown, so
// what they read never moves until Space `l` brings the latest in
// (`docs/dashboard.md`, *The review*, *The drawers*).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { doing, everyone, launches, ring, running, type Running } from "./agents";
import { ask, type Asked, type Replied } from "./api";
import { cited } from "./comments";
import { useNow, useWatched } from "./hooks";
import { REVIEW_KEYS, REVIEW_PLACES, type ReviewPlace } from "./keys";
import { Keys } from "./Keys";
import { Palette } from "./Palette";
import { Review, type Jump } from "./Review";
import {
    UNREAD,
    answer,
    changing,
    covered,
    currentTask,
    EMPTY,
    flag,
    messages,
    pruned,
    remarks,
    whose,
    type AgentDrawers,
    type Answered,
    type ChangedFile,
    type Context,
    type Conversation as InboxConversation,
    type Draft,
    type Drawers,
    type Head,
    type Item,
    type Since,
} from "./review";

const SAID = {
    connecting: "connecting",
    live: "live",
    retrying: "out of reach, trying again",
    refused: "this page's token is refused: open the dashboard again from `lup-dev dashboard`",
};

/** How long the page waits between reading each agent's record with no hook heard, in milliseconds: a record written just after its hook is read all the same. */
const EVERY = 5000;

/** How long the page waits between asking what each agent's branch changed since the operator approved it, in milliseconds: each asking snapshots the worktree. */
const SINCE_EVERY = 10_000;

/** A conversation running, as the review names it: with its launch's ids and its banner's parts. */
interface Live extends Running {
    conversation: InboxConversation;
    key: string;
}

export function App() {
    const { reply, connection } = useWatched({ kind: "list" });
    const inbox = useWatched({ kind: "inbox-list" });
    const now = useNow();
    // The review's ages are told to the minute, so it's laid out again once a minute, not every second; the banners'
    // durations every five seconds, which lays the whole review out again, its drawers among it.
    const minute = useNow(60_000);
    const soon = useNow(5000);
    const [palette, setPalette] = useState(false);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    const [contexts, setContexts] = useState<Map<number, Answered<Context>>>(new Map());
    const [files, setFiles] = useState<Map<number, Answered<ChangedFile[]>>>(new Map());
    const around = useMemo(() => ({ contexts, files }), [contexts, files]);
    // What the host has answered of each agent, for its banner and its drawers, by its conversation.
    const [drawers, setDrawers] = useState<Drawers>(new Map());
    // The items whose context, and whose files, were asked for, so each is asked once: an approval's files once
    // more when the judge has read their types (`typing`), each asking keyed by its number and how far along it was.
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
    // The keys of a chord begun in the review, whose following keys the line of keys shows.
    const [chord, setChord] = useState("");
    const [epoch, setEpoch] = useState(0);
    const [jump, setJump] = useState<Jump | null>(null);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const served = reply?.kind === "listed" ? launches(reply) : [];
    const agents = everyone(served);
    const talkers = useMemo(() => agents.map((each) => each.talker), [agents]);

    // A party as it's called: a conversation by its path, else by its runtime's ids.
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

    // The conversations running, in the order the host lists them: the review gives each a group.
    const live = useMemo<Live[]>(
        () =>
            running(reply?.kind === "listed" ? launches(reply) : []).map(({ launch, talker }) => {
                const conversation: InboxConversation = {
                    party: "conversation",
                    repository: launch.repository,
                    runtime: launch.runtime,
                    session: talker.session,
                    agent: talker.agent ?? null,
                };
                return { launch, talker, conversation, key: whose(conversation) };
            }),
        [reply],
    );
    const agentsRunning = useMemo(() => live.map((each) => each.conversation), [live]);

    // What the banner says of an agent beyond its name: what it's doing, what it's working on, its context, and whether its flagged writes are held.
    const banner = useCallback(
        (head: Head) => {
            const found = (party: InboxConversation) => live.find((each) => each.key === whose(party));
            if ("conversation" in head) {
                // A conversation that isn't running, written to all the same, by its runtime's ids where it isn't known.
                const agent = found(head.conversation);
                return agent === undefined ? [last(head.conversation.repository), called(head.conversation)].join(" · ") : bannered(agent);
            }
            const item = head.item;
            const sender = item.sender;
            if (sender.party === "conversation") {
                const agent = found(sender);
                if (agent !== undefined) {
                    return bannered(agent);
                }
            }
            const repository =
                sender.party === "conversation"
                    ? sender.repository
                    : item.reason.reason === "approval"
                      ? item.reason.repository
                      : null;
            const where = [repository, item.worktree ?? null].flatMap((each) => (each === null ? [] : [last(each)]));
            return [...where, sender.party === "operator" ? "lup's approvals" : named(item)].join(" · ");

            function bannered(agent: Live): string {
                const data = drawers.get(agent.key) ?? UNREAD;
                const task = currentTask(data.tasks);
                const usage = data.usage;
                return [
                    [last(agent.launch.repository), last(agent.launch.worktree), agent.talker.path].join(" · "),
                    doing(agent.talker.activity, soon),
                    ...(task === null ? [] : [`▶ ${task}`]),
                    ...(usage === null ? [] : [ring(usage.used, usage.window)]),
                    ...(agent.talker.holding === true ? ["holding"] : []),
                ].join(" · ");
            }
        },
        [named, called, live, drawers, soon],
    );

    // What waits for the operator: a flagged write is no item of the review, shown in its agent's drawer instead.
    const waiting = useMemo(
        () => (inbox.reply?.kind === "inbox-items" ? inbox.reply.items.filter((each) => !flag(each)) : []),
        [inbox.reply],
    );
    const main = useRef<HTMLElement>(null);

    /** Turn the operator's switch for the agent `conversation` is: whether each flagged write of it and its subagents is held. */
    function hold(conversation: InboxConversation) {
        const agent = live.find((each) => each.key === whose(conversation));
        if (agent === undefined) {
            setSaid("The switch is turned on an agent running.");
            return;
        }
        const on = agent.talker.holding !== true;
        const { session, agent: subagent, path } = agent.talker;
        void ask({ kind: "set-holding", launch: agent.launch.launch, session, agent: subagent ?? null, on }).then((answer) => {
            if (answer.kind === "refused") {
                setSaid(answer.error);
                return;
            }
            setSaid(
                on
                    ? `Each flagged write of ${path} and its subagents is held for your answer.`
                    : `${path}'s flagged writes land again, flagged.`,
            );
        });
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
        // Each item's context, where an agent's call made it, and each file an item changes (`changing`), asked
        // once it's in the inbox; an approval's again once the judge has read their types.
        for (const item of waiting) {
            const number = item.number;
            if (item.call != null && !asked.current.contexts.has(number)) {
                asked.current.contexts.add(number);
                void answered({ kind: "inbox-show-context", number }, (answer) =>
                    answer.kind === "inbox-context" ? answer : null,
                ).then((context) => setContexts((before) => new Map(before).set(number, context)));
            }
            const reason = item.reason;
            const stage = reason.reason === "approval" ? reason.typing : 0;
            const reading = `${number}:${stage}`;
            if (changing(item) && !asked.current.files.has(reading)) {
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

    /** Change what's held of one agent's drawers. */
    const drawn = useCallback((key: string, next: (before: AgentDrawers) => AgentDrawers) => {
        setDrawers((before) => new Map(before).set(key, next(before.get(key) ?? UNREAD)));
    }, []);

    // How many steps of each agent's record the page has, so each asking reads only what came since.
    const have = useRef(new Map<string, number>());
    const reading = useRef(false);
    const again = useRef(false);

    /** Read each agent running's record for the steps since those the page has, with its task list and its context, and the items it exchanged; again where a hook was heard meanwhile. */
    const refresh = useCallback(async () => {
        if (reading.current) {
            again.current = true;
            return;
        }
        reading.current = true;
        try {
            do {
                again.current = false;
                await Promise.all(live.map((agent) => read(agent)));
            } while (again.current);
        } finally {
            reading.current = false;
        }

        async function read(agent: Live): Promise<void> {
            const { conversation, key } = agent;
            const since = have.current.get(key) ?? 0;
            try {
                const [steps, listed] = await Promise.all([
                    ask({ kind: "inbox-show-conversation", runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null, since }),
                    ask({ kind: "inbox-list-items", conversation }),
                ]);
                const exchanged = listed.kind === "inbox-exchanged" ? { sent: listed.sent, received: listed.received } : null;
                if (steps.kind !== "inbox-conversation") {
                    drawn(key, (before) => ({ ...before, exchanged }));
                    return;
                }
                const whole = steps.total < since;
                if (whole) {
                    // The record is shorter than what the page read of it: read it again whole.
                    have.current.set(key, 0);
                    again.current = true;
                } else {
                    have.current.set(key, since + steps.entries.length);
                }
                drawn(key, (before) => ({
                    ...before,
                    entries: whole ? [] : [...before.entries, ...steps.entries],
                    tasks: steps.tasks ?? [],
                    usage: steps.usage ?? null,
                    exchanged,
                }));
            } catch (error) {
                console.warn("lup's dashboard: an agent's record couldn't be read", error);
            }
        }
    }, [live, drawn]);

    useEffect(() => {
        void refresh();
    }, [reply, refresh]);

    useEffect(() => {
        const asking = setInterval(() => void refresh(), EVERY);
        return () => clearInterval(asking);
    }, [refresh]);

    // What each agent's branch changed since the operator approved it, as the page shows it, by its conversation.
    const shown = useRef(new Map<string, Since>());

    /** Ask what `agent`'s branch changed since the operator approved it: with the version shown, kept still where it isn't the one as it stands, unless `fresh`, which brings the latest in. */
    const since = useCallback(
        async (agent: Live, fresh: boolean) => {
            const was = shown.current.get(agent.key) ?? null;
            const reply = await answered({ kind: "policy-show-since", conversation: agent.conversation, seen: fresh ? null : (was?.version ?? null) }, (answer) =>
                answer.kind === "policy-since" ? answer : null,
            );
            if (!("shown" in reply)) {
                if (fresh) {
                    setSaid(`Since you approved couldn't be read: ${reply.refused}`);
                }
                return;
            }
            const now = reply.shown;
            if (now.same) {
                return;
            }
            if (was === null || fresh) {
                shown.current.set(agent.key, now);
                drawn(agent.key, (before) => ({ ...before, since: now, latest: null }));
                return;
            }
            drawn(agent.key, (before) => ({ ...before, latest: now.version === was.version ? null : now }));
        },
        [drawn],
    );

    const refreshSince = useCallback(async () => {
        await Promise.all(live.map((agent) => since(agent, false)));
    }, [live, since]);

    useEffect(() => {
        void refreshSince();
        const asking = setInterval(() => void refreshSince(), SINCE_EVERY);
        return () => clearInterval(asking);
    }, [refreshSince]);

    /** Bring the latest of what an agent's branch changed into its drawer. */
    const bringIn = useCallback(
        (conversation: InboxConversation) => {
            const agent = live.find((each) => each.key === whose(conversation));
            if (agent !== undefined) {
                void since(agent, true);
            }
        },
        [live, since],
    );

    /** Approve the flagged writes on an agent's branch, those on `path` or every one, and read the drawer anew from what was approved. */
    const approveSince = useCallback(
        (conversation: InboxConversation, path: string | null) => {
            const agent = live.find((each) => each.key === whose(conversation));
            void ask({ kind: "policy-approve-since", conversation, path }).then((answer) => {
                if (answer.kind === "refused") {
                    setSaid(answer.error);
                    return;
                }
                if (answer.kind === "policy-approved") {
                    const flags = answer.flags;
                    setSaid(
                        flags.length === 0
                            ? `Nothing flagged${path === null ? " on the branch" : ` on ${path}`} was waiting for your approval.`
                            : `Approved ${flags.map(cited).join(", ")}${path === null ? ": the branch's landing waits on none of them" : ""}.`,
                    );
                }
                if (agent !== undefined) {
                    void since(agent, true);
                }
            });
        },
        [live, since],
    );

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
                setSaid(`${cited(number)} ${approved ? "approved" : "declined"}.`);
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
            const list = (items: { number: number }[]) => items.map((each) => cited(each.number)).join(", ");
            const approved = answer.approved ?? [];
            const noted = answer.noted ?? [];
            const kept = answer.kept ?? [];
            const done = [
                ...answer.items.map((each) => `${cited(each.number)} to ${called(each.recipient)}`),
                ...(approved.length === 0 ? [] : [`approved ${list(approved)}`]),
                ...noted.map((each) => `comments to ${called(each.recipient)} as ${cited(each.number)}`),
                ...(kept.length === 0 ? [] : [`comments on ${kept.map(cited).join(", ")} kept: no session's push asked it`]),
            ];
            setSaid(`Sent: ${done.join("; ") || "nothing new"}.`);
        }
        const after = await ask({ kind: "inbox-draft" });
        if (after.kind === "inbox-drafted") {
            setDraft(after.draft);
            setEpoch((before) => before + 1);
        }
    }

    /** Go to an agent's group, as the palette asks. */
    const goTo = useCallback(
        (path: string) => {
            const agent = live.find((each) => each.talker.path === path);
            if (agent !== undefined) {
                setJump((before) => ({ to: agent.conversation, number: (before?.number ?? 0) + 1 }));
            }
        },
        [live],
    );

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
    // Written to: each agent a message under its banner, or a remark in its drawers, is for, which the reply reaches whatever it covers.
    const letters = messages(draft);
    const remarked = remarks(draft);
    const writtenTo = [...new Set(letters.map((each) => called(each.to)))];
    const remarkedTo = [...new Set(remarked.map((each) => called(each.to)))];
    const reached = [...new Set([...writtenTo, ...remarkedTo, ...told.map(named), ...pushers])];
    const onMessages = commented.filter((number) => told.some((each) => each.number === number));
    const read = coveredItems.filter((each) => !yesOrNo(each) && !commented.includes(each.number)).map((each) => each.number);
    const citing = (list: number[]) => list.map(cited).join(", ");
    const replying = numbers.length > 0 || letters.length > 0 || remarked.length > 0;
    const covering = [
        ...(writtenTo.length === 0 ? [] : [`${letters.length === 1 ? "a message" : "messages"} to ${writtenTo.join(", ")}`]),
        ...(remarkedTo.length === 0 ? [] : [`${remarked.length === 1 ? "a remark" : `${remarked.length} remarks`} to ${remarkedTo.join(", ")}`]),
        ...(onMessages.length === 0 ? [] : [`comments on ${citing(onMessages)}`]),
        ...(read.length === 0 ? [] : [`read ${citing(read)}`]),
        ...(approving.length === 0 ? [] : [`approving ${citing(approving.map((each) => each.number))}`]),
        ...(unanswered.length === 0 ? [] : [`comments on ${citing(unanswered.map((each) => each.number))}, left unanswered`]),
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
                <span className="count">
                    {agents.length} {agents.length === 1 ? "agent" : "agents"} · {waiting.length} waiting on you
                </span>
                <button type="button" onClick={() => setPalette(true)}>
                    Go to <kbd>Ctrl</kbd> <kbd>K</kbd>
                </button>
            </header>
            <main className="win" ref={main}>
                <div className="review">
                    <Review
                        items={waiting}
                        agents={agentsRunning}
                        draft={draft}
                        change={change}
                        banner={banner}
                        called={called}
                        around={around}
                        drawers={drawers}
                        send={() => {
                            if (replying) {
                                void sent();
                            }
                        }}
                        approve={approve}
                        approveSince={approveSince}
                        latest={bringIn}
                        hold={hold}
                        jump={jump}
                        say={setSaid}
                        inserting={setInserting}
                        epoch={epoch}
                        placed={setPlace}
                        pending={setChord}
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
                            <span className="muted"> Later: {(draft.parked ?? []).map(cited).join(", ")}.</span>
                        )}
                    </div>
                    <Keys
                        parts={REVIEW_KEYS}
                        place={inserting ? "insert" : place}
                        places={REVIEW_PLACES}
                        open={listing}
                        setOpen={setListing}
                        pending={chord}
                    />
                </div>
            </main>
            <Palette open={palette} setOpen={setPalette} agents={agents} select={goTo} now={now} />
        </div>
    );
}

/** Ask the host for more than the inbox's own text: what `shown` takes from its reply, or why it refused, or why it couldn't be asked. */
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
