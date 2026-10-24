// The page: everything waiting for the operator as one review in groups, one
// per agent, every agent running having one, its banner saying what the agent
// is doing, what it's working on and its context, its drawers at the group's end
// holding its tasks, what its branch changed since the operator approved it and
// its whole conversation; the operator's reply written into it,
// their messages to agents and their remarks in the drawers among it, and a line
// saying what the reply covers and who it reaches: every agent it covers or
// writes to, each getting all of it. The palette (Ctrl+K) goes to an agent's
// group. Each agent's record is read at each of its hooks the host hears, which
// the listing watched says (`Talker.activity`), and as its conversation drawer
// opens, for its banner and its drawers, each call read whole as its fold opens,
// again as the record grows where it hadn't returned; what its branch changed
// since the operator last saw it as a call of its that may have written ends and
// as its drawer opens, with the version shown, so the host answers without the
// files where nothing changed, and laid out as it comes, live; each a minute
// apart at most; a file marked reviewed there a line at once, as the host's
// answer confirms or brings it back (`docs/dashboard.md`, *The review*, *The
// drawers*).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { doing, everyone, launches, ring, running, type Activity, type Agent, type Running } from "./agents";
import { ask, type Asked, type Replied } from "./api";
import { cited } from "./comments";
import { useNow, useSame, useWatched } from "./hooks";
import { REVIEW_KEYS, REVIEW_PLACES, type ReviewPlace } from "./keys";
import { Keys } from "./Keys";
import { OUTLINE_KEYS } from "./Outline";
import { Palette } from "./Palette";
import { Review, type DrawerKind, type Jump } from "./Review";
import { marked, sameShown, type Marking } from "./since";
import { searchOf, trialsOf, trialsSaid, type Trials } from "./trials";
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
    type Call,
    type ChangedFile,
    type Context,
    type Conversation as InboxConversation,
    type Draft,
    type Drawers,
    type Head,
    type Item,
    type Since,
    type Viewed,
} from "./review";

/** How long the answers to items' contexts and files are gathered before the review is laid out with them, in milliseconds. */
const GATHERED = 100;

/** The answers gathered so far, and the moment they're due to be laid out, where one is set. */
interface Gathered {
    contexts: Map<number, Answered<Context>>;
    files: Map<number, Answered<ChangedFile[]>>;
    due: ReturnType<typeof setTimeout> | null;
}

const SAID = {
    connecting: "connecting",
    live: "live",
    retrying: "out of reach, trying again",
    refused: "this page's token is refused: open the dashboard again from `lup-dev dashboard`",
};

/** How long the page lets each agent's record and branch go unread with no hook heard, in milliseconds: a record written just after its hook, or a write no hook said, is read all the same. */
const FALLBACK = 60_000;

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
    // The layout trials, as the address says them, changed from the palette and written back into the address.
    const [trials, setTrials] = useState<Trials>(() => trialsOf(window.location.search));
    const choose = useCallback((next: Trials) => {
        setTrials(next);
        const url = new URL(window.location.href);
        url.search = searchOf(next, url.search);
        window.history.replaceState(window.history.state, "", url);
    }, []);
    // What's typed in the palette as it opens: "Layout" where it's opened from the bar's line saying the trials.
    const [typed, setTyped] = useState("");
    // The outline on a narrow screen, where it's an overlay its key opens.
    const [outlining, setOutlining] = useState(false);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    const [contexts, setContexts] = useState<Map<number, Answered<Context>>>(new Map());
    const [files, setFiles] = useState<Map<number, Answered<ChangedFile[]>>>(new Map());
    // The operator's own items about those waiting, and the agents' items those are on: what's shown above and under each.
    const answers = useMemo(() => (inbox.reply?.kind === "inbox-items" ? (inbox.reply.answers ?? []) : []), [inbox.reply]);
    const onItems = useMemo(() => (inbox.reply?.kind === "inbox-items" ? (inbox.reply.commented ?? []) : []), [inbox.reply]);
    const around = useMemo(() => ({ contexts, files, answers, commented: onItems }), [contexts, files, answers, onItems]);
    // What the host has answered of each agent, for its banner and its drawers, by its conversation.
    const [drawers, setDrawers] = useState<Drawers>(new Map());
    // The items whose context, and whose files, were asked for, so each is asked once: an approval's files once
    // more when the judge has read their types (`typing`), each asking keyed by its number and how far along it was.
    const asked = useRef({ contexts: new Set<number>(), files: new Set<string>() });
    // Each item's latest asking for its files, whose answer alone is shown.
    const latest = useRef(new Map<number, string>());
    // What the host answered of items, gathered for a moment (`GATHERED`) and laid out together: at load, every
    // item's files and context answer within the same second, and the review laid out once for them all costs
    // what laid out once for each would.
    const gathered = useRef<Gathered>({ contexts: new Map(), files: new Map(), due: null });
    const gather = useCallback((add: (held: Gathered) => void) => {
        const held = gathered.current;
        add(held);
        held.due ??= setTimeout(() => {
            held.due = null;
            const came = { contexts: held.contexts, files: held.files };
            held.contexts = new Map();
            held.files = new Map();
            if (came.contexts.size > 0) {
                setContexts((before) => new Map([...before, ...came.contexts]));
            }
            if (came.files.size > 0) {
                setFiles((before) => new Map([...before, ...came.files]));
            }
        }, GATHERED);
    }, []);
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
    const served = useMemo(() => (reply?.kind === "listed" ? launches(reply) : []), [reply]);
    const agents = useMemo(() => everyone(served), [served]);
    // What the review reads of the listing stays the same object while it says the same (`useSame`): the host
    // answers the watch again at every hook, with what each conversation is doing, and the review lays nothing out
    // anew for a reply that changed nothing its text says (`docs/host.md`, *Watching*).
    const talkers = useSame(
        useMemo(() => agents.map((each) => each.talker), [agents]),
        (list) => list.map((each) => `${each.session} ${each.agent ?? ""} ${each.path}`).join("\n"),
    );

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
            running(served).map(({ launch, talker }) => {
                const conversation: InboxConversation = {
                    party: "conversation",
                    repository: launch.repository,
                    runtime: launch.runtime,
                    session: talker.session,
                    agent: talker.agent ?? null,
                };
                return { launch, talker, conversation, key: whose(conversation) };
            }),
        [served],
    );
    // Each conversation's parent, by `whose` each is, as the host's tree has it: what nests a subagent's group under its parent's.
    const parents = useSame(
        useMemo(() => {
            const found = new Map<string, string>();
            for (const { launch, session } of served) {
                const keyOf = (agent: Agent) =>
                    whose({ party: "conversation", repository: launch.repository, runtime: launch.runtime, session: agent.talker.session, agent: agent.talker.agent ?? null });
                const walk = (agent: Agent) => {
                    for (const child of agent.children) {
                        found.set(keyOf(child), keyOf(agent));
                        walk(child);
                    }
                };
                if (session !== null) {
                    walk(session);
                }
            }
            return found;
        }, [served]),
        (map) => JSON.stringify([...map]),
    );
    // What each conversation running is doing, by `whose` it is, for the outline's marks.
    const states = useSame(
        useMemo(() => new Map(live.map((each) => [each.key, each.talker.activity?.state ?? null])), [live]),
        (map) => JSON.stringify([...map]),
    );
    const agentsRunning = useSame(
        useMemo(() => live.map((each) => each.conversation), [live]),
        (list) => list.map(whose).join("\n"),
    );

    // What each agent's banner says, by its conversation, kept the same object while every banner says the same
    // (`useSame`): a hook that changed nothing a banner says, or a record read that changed no task or ring, lays
    // nothing out anew; one that did changes the banner's words, which the text holds, so the review is laid out.
    const bannered = useSame(
        useMemo(() => new Map(live.map((agent) => [agent.key, bannerOf(agent, drawers.get(agent.key) ?? UNREAD, soon)])), [live, drawers, soon]),
        (map) => JSON.stringify([...map]),
    );

    // What the banner says of an agent beyond its name: what it's doing, what it's working on, its context, and whether its flagged writes are held.
    const banner = useCallback(
        (head: Head) => {
            if ("conversation" in head) {
                // A conversation that isn't running, written to all the same, by its runtime's ids where it isn't known.
                return bannered.get(whose(head.conversation)) ?? [last(head.conversation.repository), called(head.conversation)].join(" · ");
            }
            const item = head.item;
            const sender = item.sender;
            if (sender.party === "conversation") {
                const said = bannered.get(whose(sender));
                if (said !== undefined) {
                    return said;
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
        },
        [named, called, bannered],
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
                ).then((context) => gather((held) => held.contexts.set(number, context)));
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
                        gather((held) => held.files.set(number, shown));
                    }
                });
            }
        }
    }, [waiting]);

    /** Change what's held of one agent's drawers; held as it was where nothing changed (`sameDrawers`), as at a record read at a hook that wrote nothing, so the review isn't laid out anew. */
    const drawn = useCallback((key: string, next: (before: AgentDrawers) => AgentDrawers) => {
        setDrawers((before) => {
            const was = before.get(key) ?? UNREAD;
            const now = next(was);
            return sameDrawers(was, now) ? before : new Map(before).set(key, now);
        });
    }, []);

    // How many steps of each agent's record the page has, so each asking reads only what came since; and which
    // agents' records are being read, each read again after where it was asked for meanwhile.
    const have = useRef(new Map<string, number>());
    const reading = useRef(new Map<string, boolean>());

    // Each agent's calls asked for whole, by its conversation, so each is asked once, but again where the host
    // couldn't answer, and those that hadn't returned when read, asked again as the record grows; and those asked in
    // one moment, as `␣zfd` opens many, gathered into one asking.
    const callsAsked = useRef(new Map<string, Set<string>>());
    const callsRunning = useRef(new Map<string, Set<string>>());
    const callsWanted = useRef(new Map<string, { agent: Live; ids: Set<string> }>());

    /** Read the calls gathered for each agent whole, those not asked yet, one asking an agent. */
    const askCalls = useCallback(() => {
        const wanted = [...callsWanted.current.values()];
        callsWanted.current = new Map();
        for (const { agent, ids } of wanted) {
            const asked = callsAsked.current.get(agent.key) ?? new Set<string>();
            const fresh = [...ids].filter((each) => !asked.has(each));
            if (fresh.length === 0) {
                continue;
            }
            callsAsked.current.set(agent.key, new Set([...asked, ...fresh]));
            const { conversation } = agent;
            const request: Asked = { kind: "inbox-show-calls", runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null, calls: fresh };
            void answered(request, (answer) => (answer.kind === "inbox-calls" ? answer.calls : null)).then((reply) => {
                const read = new Map<string, Answered<Call>>(
                    fresh.map((id) => {
                        if ("refused" in reply) {
                            return [id, reply];
                        }
                        const found = reply.shown.find((each) => each.id === id);
                        return [id, found === undefined ? { refused: "its record doesn't hold it" } : { shown: found }];
                    }),
                );
                const running = [...read].flatMap(([id, each]) => ("shown" in each && each.shown.output == null ? [id] : []));
                callsRunning.current.set(agent.key, new Set([...(callsRunning.current.get(agent.key) ?? []), ...running]));
                // One the host couldn't read is asked again as its fold opens again.
                if ("refused" in reply) {
                    fresh.forEach((each) => callsAsked.current.get(agent.key)?.delete(each));
                }
                drawn(agent.key, (before) => ({ ...before, calls: new Map([...before.calls, ...read]) }));
            });
        }
    }, [drawn]);

    /** Read `ids` of `agent`'s calls whole, with any others asked for in the same moment. */
    const readCalls = useCallback(
        (agent: Live, ids: string[]) => {
            const held = callsWanted.current.get(agent.key) ?? { agent, ids: new Set<string>() };
            ids.forEach((each) => held.ids.add(each));
            const first = callsWanted.current.size === 0;
            callsWanted.current.set(agent.key, held);
            if (first) {
                setTimeout(askCalls, 0);
            }
        },
        [askCalls],
    );

    /** Read again `agent`'s calls that hadn't returned when they were read, its record having grown. */
    const again = useCallback(
        (agent: Live) => {
            const running = [...(callsRunning.current.get(agent.key) ?? [])];
            if (running.length === 0) {
                return;
            }
            callsRunning.current.delete(agent.key);
            const asked = callsAsked.current.get(agent.key);
            running.forEach((each) => asked?.delete(each));
            readCalls(agent, running);
        },
        [readCalls],
    );

    /** Read `agent`'s record for the steps since those the page has, with its task list and its context, and the items it exchanged; once at a time, again where asked meanwhile. */
    const readRecord = useCallback(
        async (agent: Live): Promise<void> => {
            const { conversation, key } = agent;
            if (reading.current.has(key)) {
                reading.current.set(key, true);
                return;
            }
            reading.current.set(key, false);
            try {
                let more = true;
                while (more) {
                    reading.current.set(key, false);
                    const since = have.current.get(key) ?? 0;
                    const [steps, listed] = await Promise.all([
                        ask({ kind: "inbox-show-conversation", runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null, since }),
                        ask({ kind: "inbox-list-items", conversation }),
                    ]);
                    const exchanged = listed.kind === "inbox-exchanged" ? { sent: listed.sent, received: listed.received } : null;
                    if (steps.kind !== "inbox-conversation") {
                        drawn(key, (before) => ({ ...before, exchanged }));
                    } else {
                        if (steps.entries.length > 0) {
                            again(agent);
                        }
                        const whole = steps.total < since;
                        if (whole) {
                            // The record is shorter than what the page read of it: read it again whole.
                            have.current.set(key, 0);
                            reading.current.set(key, true);
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
                    }
                    more = reading.current.get(key) === true;
                }
            } catch (error) {
                console.warn("lup's dashboard: an agent's record couldn't be read", error);
            } finally {
                reading.current.delete(key);
            }
        },
        [drawn, again],
    );

    // What each agent's branch changed since the operator last saw it, as the host last read it, by its conversation;
    // and the files of each being marked reviewed, each laid out as a reviewed line from the key's press until the
    // host answers.
    const shown = useRef(new Map<string, Since>());
    const marking = useRef(new Map<string, Marking[]>());

    /** Lay out the drawer of the agent whose conversation is `key` as the host last read it, each file being marked as its reviewed line. */
    const showSince = useCallback(
        (key: string) => {
            const now = shown.current.get(key);
            if (now !== undefined) {
                drawn(key, (before) => ({ ...before, since: marked(now, marking.current.get(key) ?? []) }));
            }
        },
        [drawn],
    );

    /** Ask what `agent`'s branch changed since the operator last saw it, with the version shown, and lay out what's changed, live; `loud` says why it couldn't be read. */
    const since = useCallback(
        async (agent: Live, loud: boolean = false) => {
            const was = shown.current.get(agent.key) ?? null;
            const reply = await answered({ kind: "policy-show-since", conversation: agent.conversation, seen: was?.version ?? null }, (answer) =>
                answer.kind === "policy-since" ? answer : null,
            );
            if (!("shown" in reply)) {
                if (loud) {
                    setSaid(`Since you approved couldn't be read: ${reply.refused}`);
                }
                return;
            }
            const now = reply.shown;
            if (now.same) {
                return;
            }
            shown.current.set(agent.key, now);
            showSince(agent.key);
        },
        [showSince],
    );

    // What each agent was last seen doing, by its conversation: a change is a hook of its the host heard.
    const seen = useRef(new Map<string, string>());

    // At each hook of an agent's, its record is read; where the hook ended a call of its that may have written,
    // a tool's that isn't lup's own, what its branch changed is read too; an agent first seen is read whole.
    useEffect(() => {
        for (const agent of live) {
            const now = JSON.stringify(agent.talker.activity ?? null);
            const before = seen.current.get(agent.key);
            if (before === now) {
                continue;
            }
            seen.current.set(agent.key, now);
            void readRecord(agent);
            const was = before === undefined ? null : (JSON.parse(before) as Activity | null);
            if (before === undefined || (was?.state === "calling" && !was.lups)) {
                void since(agent);
            }
        }
    }, [live, readRecord, since]);

    // A minute apart at most, each agent's record and branch are read again, for what no hook said.
    useEffect(() => {
        const asking = setInterval(() => {
            for (const agent of live) {
                void readRecord(agent);
                void since(agent);
            }
        }, FALLBACK);
        return () => clearInterval(asking);
    }, [live, readRecord, since]);

    /** Read what an agent's drawer shows as it opens: its record for the conversation, its branch for "since you approved". */
    const opened = useCallback(
        (conversation: InboxConversation, kind: DrawerKind) => {
            const agent = live.find((each) => each.key === whose(conversation));
            if (agent === undefined) {
                return;
            }
            if (kind === "since") {
                void since(agent, true);
            } else if (kind !== "tasks") {
                void readRecord(agent);
            }
        },
        [live, readRecord, since],
    );

    /** Read an agent's calls whole as their folds open. */
    const details = useCallback(
        (conversation: InboxConversation, ids: string[]) => {
            const agent = live.find((each) => each.key === whose(conversation));
            if (agent !== undefined) {
                readCalls(agent, ids);
            }
        },
        [live, readCalls],
    );

    /**
     * Mark files of an agent's branch reviewed at the versions shown, approving their flags where they stand so: each a
     * reviewed line at once, the host's answer saying what came of it. Where the drawer stood as the page shows it, the
     * answer is the drawer as it stands, taken in; else it's read anew, bringing back each file that moved since it was
     * shown, its flags waiting. Refused, each is as it was.
     */
    const reviewSince = useCallback(
        (conversation: InboxConversation, files: Viewed[]) => {
            const key = whose(conversation);
            const agent = live.find((each) => each.key === key);
            const was = shown.current.get(key) ?? null;
            const at = new Date().toISOString();
            const mine: Marking[] = files.map((each) => ({ path: each.path, version: each.version ?? null, at }));
            marking.current.set(key, [...(marking.current.get(key) ?? []), ...mine]);
            showSince(key);
            const request: Asked = { kind: "policy-review-since", conversation, files, seen: was?.version ?? null };
            void answered(request, (answer) => (answer.kind === "policy-reviewed" ? answer : null)).then(async (reply) => {
                if ("refused" in reply) {
                    setSaid(`Not marked reviewed: ${reply.refused}`);
                } else {
                    const answer = reply.shown;
                    setSaid(reviewedSaid(answer.reviewed, answer.approved ?? [], answer.moved ?? []));
                    if (was !== null && answer.version != null && shown.current.get(key) === was) {
                        const marked = new Map((answer.files ?? []).map((each) => [each.path, each]));
                        shown.current.set(key, { ...was, version: answer.version, files: (was.files ?? []).map((each) => marked.get(each.path) ?? each) });
                    } else if (agent !== undefined) {
                        await since(agent, true);
                    }
                }
                const left = (marking.current.get(key) ?? []).filter((each) => !mine.includes(each));
                if (left.length === 0) {
                    marking.current.delete(key);
                } else {
                    marking.current.set(key, left);
                }
                showSince(key);
            });
        },
        [live, since, showSince],
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
                <button
                    type="button"
                    className="trials"
                    title="The layout trials: Ctrl+K, Layout"
                    onClick={() => {
                        setTyped("Layout");
                        setPalette(true);
                    }}
                >
                    layout: {trialsSaid(trials)}
                </button>
                {trials.outline === "pane" ? (
                    <button type="button" className="outline-button" onClick={() => setOutlining((before) => !before)}>
                        Outline <kbd>gO</kbd>
                    </button>
                ) : null}
                <button
                    type="button"
                    onClick={() => {
                        setTyped("");
                        setPalette(true);
                    }}
                >
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
                        reviewSince={reviewSince}
                        hold={hold}
                        opened={opened}
                        details={details}
                        jump={jump}
                        say={setSaid}
                        inserting={setInserting}
                        epoch={epoch}
                        placed={setPlace}
                        pending={setChord}
                        list={openList}
                        reviewed={inbox.reply?.kind === "inbox-items" ? (inbox.reply.reviewed ?? null) : null}
                        now={minute}
                        trials={trials}
                        parents={parents}
                        states={states}
                        outlining={outlining}
                        setOutlining={setOutlining}
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
                        parts={trials.outline === "off" ? REVIEW_KEYS : [...REVIEW_KEYS, ...OUTLINE_KEYS]}
                        place={inserting ? "insert" : place}
                        places={REVIEW_PLACES}
                        open={listing}
                        setOpen={setListing}
                        pending={chord}
                    />
                </div>
            </main>
            <Palette
                open={palette}
                setOpen={(open) => {
                    setPalette(open);
                    if (!open) {
                        setTyped("");
                    }
                }}
                agents={agents}
                select={goTo}
                now={now}
                trials={trials}
                choose={choose}
                typed={typed}
            />
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

/** Say an agent's banner beyond its name: where it is, what it's doing as of `now`, what it's working on, its context, and whether its flagged writes are held. */
function bannerOf(agent: Live, data: AgentDrawers, now: Date): string {
    const task = currentTask(data.tasks);
    const usage = data.usage;
    return [
        [last(agent.launch.repository), last(agent.launch.worktree), agent.talker.path].join(" · "),
        doing(agent.talker.activity, now),
        ...(task === null ? [] : [`▶ ${task}`]),
        ...(usage === null ? [] : [ring(usage.used, usage.window)]),
        ...(agent.talker.holding === true ? ["holding"] : []),
    ].join(" · ");
}

/** Say what marking files reviewed came to: how many, the flagged writes approved with them, and those that changed since the version shown, whose flags wait. */
function reviewedSaid(reviewed: string[], approved: number[], moved: string[]): string {
    const files = reviewed.length === 1 ? (reviewed[0] ?? "") : `${reviewed.length} files`;
    const flags = approved.length === 0 ? "" : `, approving ${approved.map(cited).join(", ")}`;
    const waiting =
        moved.length === 0
            ? ""
            : ` ${moved.length === 1 ? moved[0] : `${moved.length} files`} changed since you read ${moved.length === 1 ? "it" : "them"}: shown with what came, ${moved.length === 1 ? "its" : "their"} flags waiting.`;
    return `Reviewed ${files}${flags}.${waiting}`;
}

/** Whether two of what's held of an agent's drawers say the same: as many steps of its record and the same calls read whole, its branch shown the same, and the same tasks, context and items exchanged. */
function sameDrawers(a: AgentDrawers, b: AgentDrawers): boolean {
    const sameSince = (x: Since | null, y: Since | null) => x === y || (x !== null && y !== null && sameShown(x, y));
    return (
        a.entries.length === b.entries.length &&
        a.calls === b.calls &&
        sameSince(a.since, b.since) &&
        JSON.stringify([a.tasks, a.usage, a.exchanged]) === JSON.stringify([b.tasks, b.usage, b.exchanged])
    );
}
