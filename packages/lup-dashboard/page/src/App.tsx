// The page: everything waiting for the operator as one review in groups, one
// per agent, every agent running having one, its banner saying what the agent
// is doing, what they're working on and their context, its drawers at the
// group's end holding their tasks, their whole conversation and what their branch
// changed since the operator approved it; the operator's reply written into it,
// their messages to agents and their remarks in the drawers among it, and what
// they mark, and a line saying what the next Ctrl+Enter sends, to each agent it
// reaches, each getting all of it, and what it marks; Ctrl+Enter sends the
// inbox's part, then applies each other mark (`sent`). The palette (Ctrl+K) goes to an agent's
// group. Each agent's record is read at each of their hooks the host hears, which
// the listing watched says (`Talker.activity`), and as their conversation drawer
// opens, for their banner and their drawers, each call read whole as its fold
// opens, again as the record grows where it hadn't returned; what their branch
// changed since the operator last saw it as a call of theirs that may have written
// ends and as their drawer opens, with the version shown, so the host answers without the
// files where nothing changed, and laid out as it comes, live; each a minute
// apart at most; a file marked reviewed there, as the reply is sent, a line at
// once, as the host's answer confirms or brings it back (`docs/dashboard.md`,
// *The review*, *The drawers*).
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, launches, ring, running, type Activity, type Agent, type Running } from "./agents";
import { ask, type Asked, type Replied } from "./api";
import { cited } from "./comments";
import { useNow, useSame, useViews, useWatched } from "./hooks";
import { movedSaid, type Marked, type Moved } from "./grammar";
import { feed } from "./editor";
import { reviewKeys, type Here } from "./keys";
import { Keys } from "./Keys";
import { adopt, merged } from "./looks";
import { instanceOf, type Instance } from "./views";
import { producerOf } from "./views/index";
import { useNarrow } from "./Outline";
import { Palette } from "./Palette";
import { Review, type DrawerKind, type Jump } from "./Review";
import { isPlace, marked, sameShown, type Marking } from "./since";
import {
    UNREAD,
    changing,
    covered,
    EMPTY,
    flag,
    messages,
    pruned,
    remarks,
    seeingOf,
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
    type Keeping,
    type Since,
    type Viewed,
    type Wait,
} from "./review";

/** How long the answers to items' contexts and files are gathered before the review is laid out with them, in milliseconds. */
const GATHERED = 100;

/**
 * How long typing in a comment pauses before the review is laid out with what was typed, in milliseconds. The editor
 * shows each key at once; laying the whole review out at each one, before it was drawn, was what made typing lag by
 * seconds on a large review (#341).
 */
const TYPED = 300;

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

/** What the review is laid out from before it's all read: no item, and no conversation running. */
const NONE: Item[] = [];
const NO_ONE: InboxConversation[] = [];

/** How long the page lets each agent's record and branch go unread with no hook heard, in milliseconds: a record written just after its hook, or a write no hook said, is read all the same. */
const FALLBACK = 60_000;

/** A conversation running, as the review names them: with their launch's ids and their banner's parts. */
/** One place of an agent's "since you approved" a marking names: its worktree and its branch, as the host answered them. */
interface Placing {
    worktree: string | null;
    branch: string | null;
}

interface Live extends Running {
    conversation: InboxConversation;
    key: string;
}

export function App() {
    const { reply, connection } = useWatched({ kind: "list" });
    const inbox = useWatched({ kind: "inbox-list" });
    // Where the review's groups go, as the host keeps it for every page and across reloads: none until it's read, and
    // none kept where the host doesn't answer it.
    const order = useWatched({ kind: "inbox-order" });
    const kept = useSame(
        useMemo(() => (order.reply === null ? null : order.reply.kind === "inbox-ordered" ? (order.reply.order.places ?? []) : []), [order.reply]),
        (places) => JSON.stringify(places),
    );
    const now = useNow();
    const [palette, setPalette] = useState(false);
    // Whether the overview pane is shown: beside the review, hidden by `\`; over it on a narrow screen, opened by `gO`.
    const narrow = useNarrow();
    const [overview, setOverview] = useState(() => !window.matchMedia("(max-width: 640px)").matches);
    const was = useRef(narrow);
    useEffect(() => {
        // Going narrow, it's put away to be opened over the review; going wide, it's beside it again.
        if (was.current !== narrow) {
            was.current = narrow;
            setOverview(!narrow);
        }
    }, [narrow]);
    const [draft, setDraft] = useState<Draft>(EMPTY);
    // What the operator's comments imply, a comment counting as a review, as the review last laid it out: shown and
    // sent with the draft's own marks.
    const [implied, setImplied] = useState<readonly Marked[]>([]);
    const implying = useCallback((marks: Marked[]) => setImplied((before) => (JSON.stringify(before) === JSON.stringify(marks) ? before : marks)), []);
    // Whether the draft has been asked for, answered or not: with the inbox, the conversations running and the order,
    // what the review is laid out from, none of which it's laid out without, lest it tell the host its groups are gone.
    const [draftRead, setDraftRead] = useState(false);
    const [contexts, setContexts] = useState<Map<number, Answered<Context>>>(new Map());
    const [files, setFiles] = useState<Map<number, Answered<ChangedFile[]>>>(new Map());
    // The operator's own items about those waiting, and the agents' items those are on: what's shown above and under each.
    const answers = useMemo(() => (inbox.reply?.kind === "inbox-items" ? (inbox.reply.answers ?? []) : []), [inbox.reply]);
    const onItems = useMemo(() => (inbox.reply?.kind === "inbox-items" ? (inbox.reply.commented ?? []) : []), [inbox.reply]);
    const around = useMemo(() => ({ contexts, files, answers, commented: onItems }), [contexts, files, answers, onItems]);
    // How far the operator has seen each group, and the items they commented on in a reply sent: what's new to them.
    const seeing = useMemo(() => seeingOf(inbox.reply?.kind === "inbox-items" ? inbox.reply : null), [inbox.reply]);
    // What the host has answered of each agent, for their banner and their drawers, by their conversation.
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
    // What the review's cursor is on and what each verb would do to it, and whether the list of every key is open: what the line of keys says.
    const [here, setHere] = useState<Here>({ on: "nothing waiting", reached: [] });
    const [listing, setListing] = useState(false);
    const openList = useCallback(() => setListing(true), []);
    // The keys of a chord begun in the review, whose following keys the line of keys shows.
    const [chord, setChord] = useState("");
    const [epoch, setEpoch] = useState(0);
    const [jump, setJump] = useState<Jump | null>(null);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const served = useMemo(() => (reply?.kind === "listed" ? launches(reply) : []), [reply]);
    // How the views look, each repository's as its process said it and lup's default standing in for the rest, merged:
    // the same object while the listing says the same of them, which it says again at every hook.
    const declared = useSame(
        useMemo(() => (reply?.kind === "listed" ? { looks: reply.looks ?? {}, standing: reply.standing } : null), [reply]),
        (each) => JSON.stringify(each),
    );
    const looks = useMemo(() => {
        const made = declared === null ? merged({}, { folds: [], tones: [], drawers: [], banners: [], verbs: [] }) : merged(declared.looks, declared.standing);
        // Taken as what's merged now before anything is drawn by it: the keys, the margin and the fold keys read it as they act.
        adopt(made);
        return made;
    }, [declared]);
    const parts = useMemo(() => reviewKeys(looks.kinds, looks.verbs), [looks]);
    // A fold kind of another repository's taking a letter one already took is refused it, and said.
    useEffect(() => {
        if (looks.refused.length > 0) {
            setSaid(looks.refused.join(" "));
        }
    }, [looks]);
    const agents = useMemo(() => everyone(served), [served]);
    // What the review reads of the listing stays the same object while it says the same (`useSame`): the host
    // answers the watch again at every hook, with what each conversation is doing, and the review lays nothing out
    // anew for a reply that changed nothing its text says (`docs/host.md`, *Watching*).
    const talkers = useSame(
        useMemo(() => agents.map((each) => each.talker), [agents]),
        (list) => list.map((each) => `${each.session} ${each.agent ?? ""} ${each.path}`).join("\n"),
    );

    // Each conversation the inbox's items name, with their path as the host names it, by `whose` they are: what names
    // an agent who isn't running, or isn't their launch's latest session, which no launch listed names.
    const paths = useMemo(
        () => new Map((inbox.reply?.kind === "inbox-items" ? (inbox.reply.paths ?? []) : []).map((each) => [whose(each.conversation), each])),
        [inbox.reply],
    );
    // A party as they're called: a conversation by their path, as their launch names it while they run, else as the
    // host does, their runtime's ids beside it where another conversation shares the path; by those ids where they have
    // none.
    const called = useCallback(
        (party: Item["sender"]) => {
            if (party.party === "operator") {
                return "you";
            }
            const talker = talkers.find(
                (each) => each.session === party.session && (each.agent ?? null) === (party.agent ?? null),
            );
            const named = paths.get(whose(party));
            const ids = `${party.runtime} ${party.session}${party.agent ? ` / ${party.agent}` : ""}`;
            const path = talker?.path ?? named?.path;
            if (path === undefined) {
                return ids;
            }
            return named?.alike === true ? `${path} (${ids})` : path;
        },
        [talkers, paths],
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
    // Each conversation's parent, by `whose` each is, as the host's tree has it: what nests a subagent's group under their parent's.
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
    // What each conversation running is doing, by `whose` they are, for the overview's marks.
    const states = useSame(
        useMemo(() => new Map(live.map((each) => [each.key, each.talker.activity?.state ?? null])), [live]),
        (map) => JSON.stringify([...map]),
    );
    const agentsRunning = useSame(
        useMemo(() => live.map((each) => each.conversation), [live]),
        (list) => list.map(whose).join("\n"),
    );
    // The landings waiting on the operator, as the host keeps them while each call waits: each file of one held in its
    // writer's "since you approved", and their banners saying it.
    const landingsWatch = useWatched({ kind: "policy-show-landings" });
    const landings = useSame(
        useMemo<readonly Wait[]>(() => (landingsWatch.reply?.kind === "policy-landings" ? (landingsWatch.reply.waiting ?? []) : []), [landingsWatch.reply]),
        (list) => JSON.stringify(list),
    );
    // Each agent not running whose drawer holds what waits on the operator: their flagged writes waiting, or files a
    // landing waits on. They keep their group, ended or not, so what waits is answered where it's shown.
    const holders = useSame(
        useMemo(() => {
            const found = new Map<string, InboxConversation>();
            const items = inbox.reply?.kind === "inbox-items" ? inbox.reply.items : [];
            for (const item of items) {
                if (flag(item) && item.sender.party === "conversation") {
                    found.set(whose(item.sender), item.sender);
                }
            }
            for (const wait of landings) {
                for (const file of wait.files ?? []) {
                    for (const writer of file.writers ?? []) {
                        found.set(whose(writer), writer);
                    }
                }
            }
            const runningKeys = new Set(live.map((each) => each.key));
            return [...found.values()].filter((each) => !runningKeys.has(whose(each)));
        }, [inbox.reply, landings, live]),
        (list) => list.map(whose).join("\n"),
    );
    // Those the review gives a group with nothing to answer: each conversation running, then each holding what waits.
    const agentsShown = useSame(
        useMemo(() => [...agentsRunning, ...holders], [agentsRunning, holders]),
        (list) => list.map(whose).join("\n"),
    );

    // What each agent's banner says, by their conversation, kept the same object while every banner says the same
    // (`useSame`): where they are, which changes only as they move, so the review is laid out anew for them alone then.
    const bannered = useSame(
        useMemo(() => new Map(live.map((agent) => [agent.key, bannerOf(agent)])), [live]),
        (map) => JSON.stringify([...map]),
    );
    // What each agent's doing, by their conversation, which their banner draws beside its words as the time passes
    // (`ticking.ts`): a hook changes it, and lays nothing out.
    const activities = useSame(
        useMemo(() => new Map(live.map((agent) => [agent.key, agent.talker.activity ?? null])), [live]),
        (map) => JSON.stringify([...map]),
    );

    // Each conversation running, by `whose` they are: which of their banner's parts their views say, and what holding
    // their writes asks.
    const runningNow = useSame(
        useMemo(() => new Map(live.map((agent) => [agent.key, { launch: agent.launch.launch, holding: agent.talker.holding === true }])), [live]),
        (map) => JSON.stringify([...map]),
    );
    // Each view of an agent's the page doesn't lay out itself, a drawer their repository's modules place, asked of the
    // host for each agent running; and each a fold of theirs reads as it opens, once opened.
    const [loads, setLoads] = useState<Instance[]>([]);
    const placed = useMemo(
        () =>
            live.flatMap(({ conversation }) =>
                looks.drawers(conversation.repository).flatMap((each) =>
                    producerOf(each.module, each.view) === undefined
                        ? [{ repository: conversation.repository, module: each.module, view: each.view, argument: { runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null } }]
                        : [],
                ),
            ),
        [live, looks],
    );
    const remote = useViews(useMemo(() => [...placed, ...loads], [placed, loads]));
    const load = useCallback((view: Instance) => {
        const id = instanceOf(view.repository, view.module, view.view, view.argument);
        setLoads((before) => (before.some((each) => instanceOf(each.repository, each.module, each.view, each.argument) === id) ? before : [...before, view]));
    }, []);
    // What the banner says of an agent beyond their name: where they are, the core's, what they're doing drawn after it;
    // what they're working on, their context and whether their flagged writes are held are their banner's parts, which
    // their views say (`views/`).
    const banner = useCallback(
        (head: Head) => {
            if ("conversation" in head) {
                // A conversation that isn't running, written to all the same, by their runtime's ids where they aren't known.
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

    /** Return the conversation running the switch `argument` turns is of, by their launch, session and subagent; none for one not running. */
    function holderOf(argument: { launch?: string; session?: string; agent?: string | null }): Live | undefined {
        return live.find((each) => each.launch.launch === argument.launch && each.talker.session === argument.session && (each.talker.agent ?? null) === (argument.agent ?? null));
    }

    /** Turn the operator's switch as the mark `argument` recorded asks (`set-holding`): whether each flagged write of an agent and their subagents is held. Return what came of it, and whether it was turned. */
    async function holding(argument: { launch?: string; session?: string; agent?: string | null; on?: boolean }): Promise<{ ok: boolean; said: string }> {
        const agent = holderOf(argument);
        if (agent === undefined) {
            return { ok: false, said: "the switch is turned on an agent running" };
        }
        const on = argument.on === true;
        const answer = await ask({ kind: "set-holding", launch: agent.launch.launch, session: agent.talker.session, agent: agent.talker.agent ?? null, on });
        if (answer.kind === "refused") {
            return { ok: false, said: answer.error };
        }
        const path = agent.talker.path;
        return { ok: true, said: on ? `each flagged write of ${path} and their subagents held for your answer` : `${path}'s flagged writes landing again, flagged` };
    }

    useEffect(() => {
        void ask({ kind: "inbox-draft" })
            .then((answer) => {
                if (answer.kind === "inbox-drafted") {
                    setDraft(answer.draft);
                    setEpoch((before) => before + 1);
                }
            })
            .finally(() => setDraftRead(true));
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
    // What's typed in a comment, the editor showing it already, not yet laid out: the review lays it out once typing
    // pauses (`TYPED`), or at once as anything else lays it out.
    const typed = useRef<Draft | null>(null);
    const typing = useRef<ReturnType<typeof setTimeout> | null>(null);

    // What the review is laid out from, all of it read: until then it's laid out empty, and the host told nothing; nor
    // where the host refused one of them, the review showing what it can.
    const ready = draftRead && kept !== null && inbox.reply !== null && reply !== null;
    const whole = reply?.kind === "listed" && inbox.reply?.kind === "inbox-items" && order.reply?.kind === "inbox-ordered";
    const keepOrder = useCallback((keeping: Keeping) => {
        void ask({ kind: "inbox-keep-order", ...keeping }).then((answer) => {
            if (answer.kind === "refused") {
                setSaid(answer.error);
            }
        });
    }, []);

    const change = useCallback((next: Draft, typedOnly: boolean = false) => {
        if (typing.current !== null) {
            clearTimeout(typing.current);
            typing.current = null;
        }
        if (typedOnly) {
            typed.current = next;
            typing.current = setTimeout(() => {
                typing.current = null;
                const now = typed.current;
                typed.current = null;
                if (now !== null) {
                    setDraft(now);
                }
            }, TYPED);
        } else {
            typed.current = null;
            setDraft(next);
        }
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

    // How many steps of each agent's record the page has read, so each asking reads only what came since, for their
    // task list and their context; and which agents' records are being read, each read again after where it was asked
    // for meanwhile. Their conversation is `Transcripts`' view, watched on the host.
    const have = useRef(new Map<string, number>());
    const reading = useRef(new Map<string, boolean>());

    /** Read `agent`'s record for their task list and their context, past the steps the page has read of it; once at a time, again where asked meanwhile. */
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
                    const steps = await ask({ kind: "inbox-show-conversation", runtime: conversation.runtime, session: conversation.session, agent: conversation.agent ?? null, since });
                    if (steps.kind === "inbox-conversation") {
                        if (steps.total < since) {
                            // The record is shorter than what the page read of it: read it again from its start.
                            have.current.set(key, 0);
                            reading.current.set(key, true);
                        } else {
                            have.current.set(key, since + steps.entries.length);
                        }
                        drawn(key, (before) => ({ ...before, tasks: steps.tasks ?? [], usage: steps.usage ?? null }));
                    }
                    more = reading.current.get(key) === true;
                }
            } catch (error) {
                console.warn("lup's dashboard: an agent's record couldn't be read", error);
            } finally {
                reading.current.delete(key);
            }
        },
        [drawn],
    );

    // What each agent's branches changed since the operator last saw them, as the host last read them, by their
    // conversation; and the files of each being marked reviewed, each laid out as a reviewed line from the key's press
    // until the host answers.
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

    /** Ask what the agent of `conversation` changed since the operator last saw it, with the version shown, and lay out what's changed, live; `loud` says why it couldn't be read. */
    const since = useCallback(
        async (conversation: InboxConversation, loud: boolean = false) => {
            const key = whose(conversation);
            const was = shown.current.get(key) ?? null;
            const reply = await answered({ kind: "policy-show-since", conversation, seen: was?.version ?? null }, (answer) =>
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
            shown.current.set(key, now);
            showSince(key);
        },
        [showSince],
    );

    // What each agent was last seen doing, by their conversation: a change is a hook of theirs the host heard.
    const seen = useRef(new Map<string, string>());

    // At each hook of an agent's, their record is read; where the hook ended a call of theirs that may have written,
    // a tool's that isn't lup's own, what their branch changed is read too; an agent first seen is read whole.
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
                void since(agent.conversation);
            }
        }
    }, [live, readRecord, since]);

    // An agent not running whose flagged writes wait, or whose files a landing waits on, is read as they're first seen,
    // and again as the landings waiting change: nothing of theirs comes at a hook.
    const heldSeen = useRef(new Set<string>());
    useEffect(() => {
        for (const conversation of holders) {
            const key = whose(conversation);
            if (!heldSeen.current.has(key)) {
                heldSeen.current.add(key);
                void since(conversation);
            }
        }
    }, [holders, since]);
    // Each writer of a file a landing waits on, and each conversation landing, read again as the landings change, those
    // of a landing done waiting among them: the drawers hold what waits, and the banners say it.
    const landed = useRef<readonly Wait[]>([]);
    useEffect(() => {
        const touched = new Map<string, InboxConversation>();
        for (const wait of [...landed.current, ...landings]) {
            touched.set(whose(wait.lander), wait.lander);
            for (const file of wait.files ?? []) {
                for (const writer of file.writers ?? []) {
                    touched.set(whose(writer), writer);
                }
            }
        }
        landed.current = landings;
        for (const conversation of touched.values()) {
            void since(conversation);
        }
    }, [landings, since]);

    // A minute apart at most, each agent's record and branches are read again, for what no hook said.
    useEffect(() => {
        const asking = setInterval(() => {
            for (const agent of live) {
                void readRecord(agent);
                void since(agent.conversation);
            }
            for (const conversation of holders) {
                void since(conversation);
            }
        }, FALLBACK);
        return () => clearInterval(asking);
    }, [live, holders, readRecord, since]);

    /** Read what an agent's drawer shows as it opens: their branches for "since you approved"; a module's view is watched already. */
    const opened = useCallback(
        (conversation: InboxConversation, kind: DrawerKind) => {
            if (kind === "since") {
                void since(conversation, true);
            }
        },
        [since],
    );

    /**
     * Mark files of one of an agent's places reviewed at the versions shown, approving their flags where they stand so,
     * or, `decline`, declining their landing, as the reply is sent: each a reviewed line at once, the host's answer
     * saying what came of it. Where the drawer stood as the page shows it, the answer is the drawer as it stands, taken
     * in; else it's read anew, bringing back each file that moved since it was shown, its flags waiting. Refused, each
     * is as it was. Return what came of it, and whether the host marked them.
     */
    const reviewSince = useCallback(
        async (conversation: InboxConversation, place: Placing, files: Viewed[], decline: boolean): Promise<{ ok: boolean; said: string }> => {
            const key = whose(conversation);
            const was = shown.current.get(key) ?? null;
            const at = new Date().toISOString();
            const mine: Marking[] = files.map((each) => ({ worktree: place.worktree, branch: place.branch, path: each.path, version: each.version ?? null, at }));
            marking.current.set(key, [...(marking.current.get(key) ?? []), ...mine]);
            showSince(key);
            const request: Asked = { kind: "policy-review-since", conversation, worktree: place.worktree, branch: place.branch, files, seen: was?.version ?? null, decline };
            const reply = await answered(request, (answer) => (answer.kind === "policy-reviewed" ? answer : null));
            let came: { ok: boolean; said: string };
            if ("refused" in reply) {
                came = { ok: false, said: `${decline ? "landing not declined" : "not marked reviewed"}: ${reply.refused}` };
            } else {
                const answer = reply.shown;
                came = { ok: true, said: reviewedSaid(answer.reviewed, answer.approved ?? [], answer.moved ?? [], answer.declined ?? []) };
                if (was !== null && answer.version != null && shown.current.get(key) === was) {
                    const marked = new Map((answer.files ?? []).map((each) => [each.path, each]));
                    const places = (was.places ?? []).map((each) =>
                        isPlace(each, place.worktree, place.branch) ? { ...each, files: (each.files ?? []).map((file) => marked.get(file.path) ?? file) } : each,
                    );
                    shown.current.set(key, { ...was, version: answer.version, places });
                } else {
                    await since(conversation, true);
                }
            }
            const left = (marking.current.get(key) ?? []).filter((each) => !mine.includes(each));
            if (left.length === 0) {
                marking.current.delete(key);
            } else {
                marking.current.set(key, left);
            }
            showSince(key);
            return came;
        },
        [since, showSince],
    );

    /**
     * Apply each mark of `marks`, as the reply is sent: the files of "since you approved" marked reviewed together, one
     * asking for each agent, and each agent's switch turned. Return the ids of those applied, and what came of each;
     * one the host refused, or no request answers yet, stays drafted, said.
     */
    // lup: defer(issue=113, why="the page sends each mark's request at Ctrl+Enter until a module's actions are a door: then Ctrl+Enter has the host call each mark's declared action in the repository's process, so a send can't stop partway")
    async function applying(marks: readonly Marked[]): Promise<{ applied: string[]; said: string[] }> {
        const applied: string[] = [];
        const said: string[] = [];
        const reviews = new Map<string, { conversation: InboxConversation; place: Placing; decline: boolean; files: Viewed[]; ids: string[] }>();
        const moving = new Map<string, { repository: string; module: string; marks: { key: Record<string, unknown>; up_to: string | null }[]; ids: string[] }>();
        for (const mark of marks) {
            switch (mark.action) {
                case "policy-review-since": {
                    const argument = mark.argument as { conversation: InboxConversation; worktree?: string | null; branch?: string | null; files: Viewed[]; decline?: boolean };
                    const place = { worktree: argument.worktree ?? null, branch: argument.branch ?? null };
                    const decline = argument.decline === true;
                    // One asking for each agent's place, and for marking or declining there.
                    const key = JSON.stringify([whose(argument.conversation), place.worktree, place.branch, decline]);
                    const was = reviews.get(key) ?? { conversation: argument.conversation, place, decline, files: [], ids: [] };
                    const paths = new Set(was.files.map((each) => each.path));
                    // One file marked, at the version its mark says: a comment's, the version it was written on.
                    const version = mark.version ?? null;
                    const files = argument.files.length === 1 && version !== null ? argument.files.map((each) => ({ ...each, version })) : argument.files;
                    reviews.set(key, { ...was, files: [...was.files, ...files.filter((each) => !paths.has(each.path))], ids: [...was.ids, mark.id] });
                    break;
                }
                case "review-mark": {
                    const argument = mark.argument as unknown as Moved;
                    const key = JSON.stringify([argument.repository, argument.module]);
                    const was = moving.get(key) ?? { repository: argument.repository, module: argument.module, marks: [], ids: [] };
                    moving.set(key, { ...was, marks: [...was.marks, { key: argument.key, up_to: argument.up_to ?? null }], ids: [...was.ids, mark.id] });
                    break;
                }
                case "set-holding": {
                    const came = await holding(mark.argument as { launch?: string; session?: string; agent?: string | null; on?: boolean });
                    said.push(came.said);
                    if (came.ok) {
                        applied.push(mark.id);
                    }
                    break;
                }
                default:
                    said.push(`${mark.says}: nothing applies it yet, kept drafted`);
            }
        }
        for (const each of reviews.values()) {
            const came = await reviewSince(each.conversation, each.place, each.files, each.decline);
            said.push(came.said);
            if (came.ok) {
                applied.push(...each.ids);
            }
        }
        // Each module's review marks of a repository moved together, as the host keeps them.
        for (const each of moving.values()) {
            const request: Asked = { kind: "review-mark", repository: each.repository, module: each.module, marks: each.marks };
            const reply = await answered(request, (answer) => (answer.kind === "review-moved" ? answer : null));
            if ("refused" in reply) {
                said.push(`not marked: ${reply.refused}`);
            } else {
                applied.push(...each.ids);
                said.push(...marks.filter((mark) => each.ids.includes(mark.id)).map((mark) => movedSaid(mark, called)));
            }
        }
        return { applied, said };
    }

    /**
     * Send the reply: the draft kept as it stands, then its part the inbox sends, the comments, messages and remarks and
     * each item marked done, declined or read (`inbox-send-draft`), then each other mark applied (`applying`), and the
     * draft kept without those applied. Where the inbox refuses its part, nothing is sent and every mark stays; where a
     * mark is refused after, what came before is sent, and that mark stays drafted, said.
     */
    async function sent() {
        if (keeping.current !== null) {
            clearTimeout(keeping.current);
        }
        // What's sent is what the host keeps: a draft it refuses to keep isn't sent, lest the last one kept go instead;
        // the marks the operator's comments imply among its own, applied with them.
        const drafted = typed.current ?? draft;
        const now = pruned(implied.length === 0 ? drafted : { ...drafted, marks: [...(drafted.marks ?? []), ...implied] });
        const kept = await ask({ kind: "inbox-keep-draft", draft: now });
        if (kept.kind === "refused") {
            setSaid(kept.error);
            return;
        }
        const told: string[] = [];
        if (covered(now).length > 0 || messages(now).length > 0 || remarks(now).length > 0) {
            const answer = await ask({ kind: "inbox-send-draft" });
            if (answer.kind === "refused") {
                setSaid(answer.error);
                return;
            }
            if (answer.kind === "inbox-reviewed") {
                told.push(...reviewSaid(answer, called));
            }
        }
        const after = await ask({ kind: "inbox-draft" });
        let left = after.kind === "inbox-drafted" ? after.draft : now;
        const marks = left.marks ?? [];
        if (marks.length > 0) {
            const { applied, said: came } = await applying(marks);
            told.push(...came);
            left = { ...left, marks: marks.filter((each) => !applied.includes(each.id)) };
            const keptAfter = await ask({ kind: "inbox-keep-draft", draft: left });
            if (keptAfter.kind === "refused") {
                told.push(keptAfter.error);
            }
        }
        setSaid(`Sent: ${told.join("; ") || "nothing"}.`);
        setDraft(left);
        setEpoch((before) => before + 1);
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

    const going = toSend(implied.length === 0 ? draft : { ...draft, marks: [...(draft.marks ?? []), ...implied] }, waiting, {
        called,
        named,
        holder: (argument) => holderOf(argument)?.talker.path ?? null,
    });
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
                <button type="button" className="overview-button" onClick={() => setOverview(!overview)} title="the overview of every agent and item">
                    Overview <kbd>{"\\"}</kbd>
                </button>
                <button type="button" onClick={() => setPalette(true)}>
                    Go to <kbd>Ctrl</kbd> <kbd>K</kbd>
                </button>
            </header>
            <main className="win" ref={main}>
                <div className="review">
                    <Review
                        items={ready ? waiting : NONE}
                        agents={ready ? agentsShown : NO_ONE}
                        draft={draft}
                        typed={typed}
                        change={change}
                        banner={banner}
                        called={called}
                        around={around}
                        drawers={drawers}
                        send={() => {
                            if (going.length > 0) {
                                void sent();
                            }
                        }}
                        opened={opened}
                        jump={jump}
                        say={setSaid}
                        inserting={setInserting}
                        epoch={epoch}
                        placed={setHere}
                        pending={setChord}
                        list={openList}
                        seeing={seeing}
                        implying={implying}
                        activities={activities}
                        parents={parents}
                        states={states}
                        overview={overview}
                        setOverview={setOverview}
                        order={ready ? kept : null}
                        keepOrder={whole ? keepOrder : null}
                        looks={looks}
                        running={runningNow}
                        landings={landings}
                        remote={remote}
                        load={load}
                    />
                    <div className="status">
                        {going.length === 0 ? (
                            <span className="muted">No reply drafted.</span>
                        ) : (
                            <span>
                                Your reply: {going.join(" · ")}. <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends.
                            </span>
                        )}
                        {(draft.parked ?? []).length === 0 ? null : (
                            <span className="muted"> Later: {(draft.parked ?? []).map(cited).join(", ")}.</span>
                        )}
                    </div>
                    <Keys
                        parts={parts}
                        here={here}
                        inserting={inserting}
                        run={(keys) => {
                            feed(keys);
                        }}
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

/** Say what the core says of an agent on their banner: where they are; what they're doing and for how long, drawn after it (`Review.tsx`), and their banner's parts, which their views say, come after. */
function bannerOf(agent: Live): string {
    return [last(agent.launch.repository), last(agent.launch.worktree), agent.talker.path].join(" · ");
}

/** How the line under the review names who a part of the reply reaches: a conversation as it's called, an item's sender, and the agent a switch is of, by their path. */
interface Naming {
    called: (party: Item["sender"]) => string;
    named: (item: Item) => string;
    holder: (argument: { launch?: string; session?: string; agent?: string | null }) => string | null;
}

/**
 * Say what the next Ctrl+Enter sends, by where each part goes (#264, as the page knows it): to each agent the reply
 * reaches, what reaches them, a message, a remark, the comments on their items, a question answered; then what's
 * marked, each item read, approved and declined, each agent's files of "since you approved" reviewed and their writes
 * held.
 * Nothing where nothing's drafted.
 */
export function toSend(draft: Draft, waiting: readonly Item[], naming: Naming): string[] {
    const numbers = covered(draft);
    const commented = numbers.filter((number) => (draft.comments ?? []).some((each) => each.item === number && each.text.trim() !== ""));
    const items = waiting.filter((each) => numbers.includes(each.number));
    const declined = items.filter((each) => (draft.declined ?? []).includes(each.number));
    const done = (item: Item) => (draft.done ?? []).includes(item.number);
    const asked = (item: Item) => item.reason.reason === "approval" || item.reason.reason === "held";
    // Approved by the send: an approval or a held change marked done, or only read, and a held change commented on.
    const approving = items.filter((each) => asked(each) && !declined.includes(each) && (done(each) || each.reason.reason === "held" || !commented.includes(each.number)));
    const to = new Map<string, string[]>();
    const reaching = (who: string, what: string) => to.set(who, [...(to.get(who) ?? []), what]);
    const letters = messages(draft);
    for (const [who, count] of tallyOf(letters.map((each) => naming.called(each.to)))) {
        reaching(who, count === 1 ? "a message" : `${count} messages`);
    }
    for (const [who, count] of tallyOf(remarks(draft).map((each) => naming.called(each.to)))) {
        reaching(who, count === 1 ? "a remark" : `${count} remarks`);
    }
    for (const item of items) {
        const words = commented.includes(item.number);
        if (item.reason.reason === "approval") {
            // An approval's comments go to the session whose push asked it, unanswered where it's neither marked done nor declined.
            const pusher = item.reason.pushed_by ?? null;
            if (words && pusher !== null) {
                reaching(naming.called(pusher), `comments on ${cited(item.number)}${done(item) || declined.includes(item) ? "" : ", left unanswered"}`);
            }
        } else if (words || item.reason.reason === "question") {
            reaching(naming.named(item), words ? `comments on ${cited(item.number)}` : `answering ${cited(item.number)}`);
        }
    }
    const citing = (list: readonly Item[]) => list.map((each) => cited(each.number)).join(", ");
    const read = items.filter((each) => !asked(each) && !commented.includes(each.number) && each.reason.reason !== "question");
    const reviewing = new Map<string, number>();
    const declining = new Map<string, number>();
    const marked: string[] = [];
    for (const mark of draft.marks ?? []) {
        if (mark.action === "policy-review-since") {
            const argument = mark.argument as { conversation: InboxConversation; files: Viewed[]; decline?: boolean };
            const who = naming.called(argument.conversation);
            const counting = argument.decline === true ? declining : reviewing;
            counting.set(who, (counting.get(who) ?? 0) + argument.files.length);
        } else if (mark.action === "set-holding") {
            const argument = mark.argument as { launch?: string; session?: string; agent?: string | null; on?: boolean };
            const who = naming.holder(argument) ?? "an agent no longer running";
            marked.push(argument.on === true ? `holding ${who}'s flagged writes` : `letting ${who}'s flagged writes land`);
        } else if (mark.action === "review-mark") {
            marked.push(movedSaid(mark, naming.called));
        } else {
            marked.push(mark.says);
        }
    }
    return [
        ...[...to].map(([who, what]) => `to ${who}: ${what.join(", ")}`),
        ...(read.length === 0 ? [] : [`read ${citing(read)}`]),
        ...(approving.length === 0 ? [] : [`approving ${citing(approving)}`]),
        ...(declined.length === 0 ? [] : [`declining ${citing(declined)}`]),
        ...[...reviewing].map(([who, count]) => `${count === 1 ? "a file" : `${count} files`} of ${who} reviewed`),
        ...[...declining].map(([who, count]) => `the landing of ${count === 1 ? "a file" : `${count} files`} of ${who} declined`),
        ...marked,
    ];
}

/** Return how many times each of `names` is said, in the order first said. */
function tallyOf(names: readonly string[]): Map<string, number> {
    const counted = new Map<string, number>();
    for (const each of names) {
        counted.set(each, (counted.get(each) ?? 0) + 1);
    }
    return counted;
}

/** Say what sending the inbox's part of the reply did, as the host answered: each review sent and to whom, each item marked read, approved and declined, each note left, and the comments kept. */
function reviewSaid(answer: Extract<Replied, { kind: "inbox-reviewed" }>, called: (party: Item["sender"]) => string): string[] {
    const list = (items: readonly { number: number }[]) => items.map((each) => cited(each.number)).join(", ");
    const approved = answer.approved ?? [];
    const declined = answer.declined ?? [];
    const read = answer.read ?? [];
    const kept = answer.kept ?? [];
    return [
        ...answer.items.map((each) => `${cited(each.number)} to ${called(each.recipient)}`),
        ...(read.length === 0 ? [] : [`read ${read.map(cited).join(", ")}`]),
        ...(approved.length === 0 ? [] : [`approved ${list(approved)}`]),
        ...(declined.length === 0 ? [] : [`declined ${list(declined)}`]),
        ...(answer.noted ?? []).map((each) => `comments to ${called(each.recipient)} as ${cited(each.number)}`),
        ...(kept.length === 0 ? [] : [`comments on ${kept.map(cited).join(", ")} kept: no session's push asked it`]),
    ];
}

/** Say what marking files reviewed came to: how many, the flagged writes approved with them, the files whose landing was declined, and those that changed since the version shown, whose flags wait. */
function reviewedSaid(reviewed: string[], approved: number[], moved: string[], declined: string[] = []): string {
    if (declined.length > 0) {
        return `declined the landing of ${declined.length === 1 ? declined[0] : `${declined.length} files`}`;
    }
    const files = reviewed.length === 1 ? (reviewed[0] ?? "") : `${reviewed.length} files`;
    const flags = approved.length === 0 ? "" : `, approving ${approved.map(cited).join(", ")}`;
    const waiting =
        moved.length === 0
            ? ""
            : ` ${moved.length === 1 ? moved[0] : `${moved.length} files`} changed since you read ${moved.length === 1 ? "it" : "them"}: shown with what came, ${moved.length === 1 ? "its" : "their"} flags waiting.`;
    return `reviewed ${files}${flags}${waiting === "" ? "" : `.${waiting}`}`;
}

/** Whether two of what's held of an agent's drawers say the same: their branch shown the same, and the same tasks and context. */
function sameDrawers(a: AgentDrawers, b: AgentDrawers): boolean {
    const sameSince = (x: Since | null, y: Since | null) => x === y || (x !== null && y !== null && sameShown(x, y));
    return sameSince(a.since, b.since) && JSON.stringify([a.tasks, a.usage]) === JSON.stringify([b.tasks, b.usage]);
}
