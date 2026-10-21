// One agent's conversation, opened from the tree: the whole of it from its start
// in one buffer moved through with vim (`editor.ts`), the items of lup's inbox it
// sent and was sent among its steps, watched so an answer arriving shows, what
// came before the operator's last words folded, growing as the agent works.
// Their comments are written into it under the agent's lines, Space `c` writing their
// message on the whole, and Ctrl+Enter sends them to the conversation as one
// message, through lup. As it grows, the view follows only a reader on its last
// line, or writing their message at its end; anyone else keeps their cursor,
// what they see, their open folds and what they're writing. Space `r` brings the
// review back (`docs/dashboard.md`, *The conversation*).
import { foldedRanges } from "@codemirror/language";
import { RangeSetBuilder } from "@codemirror/state";
import { Decoration, type DecorationSet, type EditorView } from "@codemirror/view";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { everyone, type Agent, type Launch } from "./agents";
import { ask, type Asked, type ReplyOf } from "./api";
import { changes, moved, saying, shownIn, type Folding, type Span } from "./comments";
import {
    UNEXCHANGED,
    UNSAID,
    aboutAt,
    folds,
    history,
    laid,
    message,
    opened,
    quoted,
    reading,
    sending,
    type Beside,
    type Earlier,
    type Entry,
    type Exchanged,
    type Laid,
    type Remark,
    type Sent,
    type Talk,
    type Whose,
} from "./conversation";
import { rebuilt, refold, useEditor } from "./editor";
import { useWatched } from "./hooks";
import { CONVERSATION_KEYS, CONVERSATION_PLACES } from "./keys";
import { Keys } from "./Keys";

interface Props {
    launch: Launch;
    agent: Agent;
    /** Changes at every hook the host hears: the conversation is asked again for what it has since. */
    beat: unknown;
    /** How many items wait in the operator's inbox, said where the review is gone back to. */
    waiting: number;
    /** Bring the review back. */
    back: () => void;
    /** Give the keyboard to the agents' tree. */
    tree: () => void;
    /** Say something in the page's top line. */
    say: (text: string) => void;
}

/** How long the page waits between asking again with no hook heard, in milliseconds: a record written just after its hook is read all the same. */
const EVERY = 5000;

/** What the page keeps of one conversation: the operator's draft on it, and what they sent it from here. */
interface Kept {
    talk: Talk;
    sent: Sent[];
}

/** Each conversation's draft and messages sent as the page last had them, by the conversation, so going back to one shows it at once while the host is asked. */
const kept = new Map<string, Kept>();

type Party = Extract<Asked, { kind: "inbox-talk" }>["conversation"];

/** How a conversation of the launch is called, by its ids. */
interface Named {
    session: string;
    agent: string | null;
    path: string;
}

/** Return what the page keeps of a conversation from what the host kept of it. */
function fromHost(talk: ReplyOf<"inbox-talked">["talk"]): Kept {
    const comments = (talk.comments ?? []).map((each) => ({
        step: each.step ?? null,
        quote: each.quote ?? null,
        text: each.text,
    }));
    return { talk: { comments }, sent: talk.sent ?? [] };
}

/** Keep what the operator wrote on `party` on the host, surviving the page's closing. */
function keepOnHost(party: Party, value: Kept, closing = false): void {
    const request: Asked = { kind: "inbox-keep-talk", conversation: party, talk: { ...value.talk, sent: value.sent } };
    if (closing) {
        void fetch("/api/ask", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify(request),
            keepalive: true,
        });
        return;
    }
    void ask(request).catch((error: unknown) => console.warn("lup's dashboard: a conversation's draft couldn't be kept", error));
}

/** Draw the conversation: what each line that isn't the agent's words shows, each comment's lines, and the passage each comment is on. */
function decorations(laidOut: Laid, talk: Talk): DecorationSet {
    const marks: { from: number; to: number; value: Decoration }[] = [];
    for (const aside of laidOut.asides) {
        marks.push({ from: aside.from, to: aside.from, value: Decoration.line({ class: `aside-${aside.kind}` }) });
    }
    for (const block of laidOut.blocks) {
        let at = block.from;
        for (const line of laidOut.text.slice(block.from, block.to).split("\n")) {
            marks.push({ from: at, to: at, value: Decoration.line({ class: "remark" }) });
            at += line.length + 1;
        }
    }
    for (const words of laidOut.words) {
        for (const block of words.blocks) {
            const quote = talk.comments[block.comment]?.quote;
            if (quote != null && quote.end > quote.start) {
                const from = shownIn(words.lines, quote.start, 0);
                const to = shownIn(words.lines, quote.end, 0);
                if (to > from) {
                    marks.push({ from, to, value: Decoration.mark({ class: "commented" }) });
                }
            }
        }
    }
    marks.sort((a, b) => a.from - b.from || a.to - b.to);
    const builder = new RangeSetBuilder<Decoration>();
    for (const each of marks) {
        builder.add(each.from, each.to, each.value);
    }
    return builder.finish();
}

/** Return whether the line at `position` is in sight. */
function inSight(view: EditorView, position: number): boolean {
    const shown = view.scrollDOM.getBoundingClientRect();
    const at = view.coordsAtPos(Math.min(position, view.state.doc.length));
    return at !== null && at.bottom > shown.top && at.top < shown.bottom;
}

const NOTHING: Laid = { text: "", words: [], asides: [], blocks: [], fold: null, items: [], turns: [], last: null, message: null };

export function Conversation({ launch, agent, beat, waiting, back, tree, say }: Props) {
    const { talker } = agent;
    const runtime = launch.launch.runtime;
    const subagent = talker.agent ?? null;
    const party = useMemo<Party>(
        () => ({ party: "conversation", repository: launch.launch.repository, runtime, session: talker.session, agent: subagent }),
        [launch.launch.repository, runtime, talker.session, subagent],
    );
    const key = JSON.stringify(party);
    const [{ talk, sent }, setKept] = useState<Kept>(() => kept.get(key) ?? { talk: UNSAID, sent: [] });
    const current = useRef<Kept>({ talk, sent });
    current.current = { talk, sent };
    // Whether the operator wrote since the conversation opened, which what the host kept doesn't replace.
    const touched = useRef(false);
    // What's written and not yet kept on the host: kept 300ms after the last change, or as the view closes.
    const pending = useRef<Kept | null>(null);
    const keeping = useRef<ReturnType<typeof setTimeout> | null>(null);
    const [entries, setEntries] = useState<Entry[]>([]);
    // What folds, once the conversation is first read: what came before the operator's last words then.
    const [folded, setFolded] = useState<Earlier | null>(null);
    // The items of lup's inbox it sent and was sent, as they stand.
    const listed = useWatched({ kind: "inbox-list-items", conversation: party });
    const exchanged = useMemo<Exchanged>(
        () => (listed.reply?.kind === "inbox-exchanged" ? listed.reply : UNEXCHANGED),
        [listed.reply],
    );
    // How each conversation of the launch is called, as text: a listing at a hook that calls them the same lays nothing out again.
    const names = useMemo(
        () =>
            JSON.stringify(
                everyone([launch]).map(({ talker: each }) => ({ session: each.session, agent: each.agent ?? null, path: each.path })),
            ),
        [launch],
    );
    const whose = useMemo<Whose>(() => {
        const called = JSON.parse(names) as Named[];
        return {
            agent: subagent,
            name: (each) =>
                called.find((found) => found.session === each.session && found.agent === (each.agent ?? null))?.path ??
                (each.agent == null ? `session ${each.session}` : `subagent ${each.agent}`),
        };
    }, [names, subagent]);
    const [refused, setRefused] = useState<string | null>(null);
    const [inserting, setInserting] = useState(false);
    // Whether the list of every key is open, and the keys of a chord begun, whose following keys are shown.
    const [listing, setListing] = useState(false);
    const [chord, setChord] = useState("");
    const [epoch, setEpoch] = useState(0);
    const have = useRef(0);
    const asking = useRef(false);
    const again = useRef(false);
    const sentNow = useRef(sent);
    sentNow.current = sent;

    const store = useCallback(
        (next: Kept, now: boolean) => {
            kept.set(key, next);
            setKept(next);
            if (keeping.current !== null) {
                clearTimeout(keeping.current);
                keeping.current = null;
            }
            if (now) {
                pending.current = null;
                keepOnHost(party, next);
                return;
            }
            pending.current = next;
            keeping.current = setTimeout(() => {
                keeping.current = null;
                pending.current = null;
                keepOnHost(party, next);
            }, 300);
        },
        [key, party],
    );

    const change = useCallback(
        (next: Talk) => {
            touched.current = true;
            store({ ...current.current, talk: next }, false);
        },
        [store],
    );

    useEffect(() => {
        // What the host kept of the conversation, where the operator hasn't begun writing since it opened.
        void ask({ kind: "inbox-talk", conversation: party })
            .then((answer) => {
                if (answer.kind === "inbox-talked" && !touched.current) {
                    const loaded = fromHost(answer.talk);
                    kept.set(key, loaded);
                    setKept(loaded);
                    setEpoch((was) => was + 1);
                }
            })
            .catch((error: unknown) => console.warn("lup's dashboard: a conversation's draft couldn't be read", error));
        // What's written and not yet kept is kept as the page closes, or as another conversation opens in this one's place.
        const flush = () => {
            if (pending.current !== null) {
                keepOnHost(party, pending.current, true);
                pending.current = null;
            }
        };
        window.addEventListener("pagehide", flush);
        return () => {
            window.removeEventListener("pagehide", flush);
            if (keeping.current !== null) {
                clearTimeout(keeping.current);
                keeping.current = null;
            }
            flush();
        };
    }, [key, party]);

    /** Ask the conversation for the steps it has since those the page has, again while a hook was heard meanwhile. */
    const refresh = useCallback(async () => {
        if (asking.current) {
            again.current = true;
            return;
        }
        asking.current = true;
        try {
            do {
                again.current = false;
                const answer = await ask({
                    kind: "inbox-show-conversation",
                    runtime,
                    session: talker.session,
                    agent: subagent,
                    since: have.current,
                });
                if (answer.kind === "refused") {
                    setRefused(answer.error);
                    setFolded((before) => before ?? "nothing");
                    continue;
                }
                if (answer.kind !== "inbox-conversation") {
                    continue;
                }
                setRefused(null);
                if (answer.total < have.current) {
                    // The record is shorter than what the page read of it: read it again whole.
                    have.current = 0;
                    setEntries([]);
                    again.current = true;
                    continue;
                }
                const arrived = answer.entries;
                const first = have.current === 0;
                have.current += arrived.length;
                setEntries((before) => (arrived.length === 0 ? before : [...before, ...arrived]));
                if (first) {
                    setFolded((before) => before ?? history(arrived, sentNow.current));
                }
            } while (again.current);
        } catch (error) {
            setRefused(error instanceof Error ? error.message : String(error));
        } finally {
            asking.current = false;
        }
    }, [runtime, talker.session, subagent]);

    useEffect(() => {
        void refresh();
    }, [beat, refresh]);

    useEffect(() => {
        const asking = setInterval(() => void refresh(), EVERY);
        return () => clearInterval(asking);
    }, [refresh]);

    const beside = useMemo<Beside>(() => ({ sent, exchanged, whose }), [sent, exchanged, whose]);
    const laidOut = useMemo(
        () => (folded === null ? NOTHING : laid(entries, beside, talk, folded)),
        [entries, beside, talk, folded],
    );
    const folding = useMemo(() => folds(laidOut), [laidOut]);
    const editor = useEditor<Talk, Remark>({
        shown: { text: laidOut.text, blocks: laidOut.blocks, folds: folding },
        draft: talk,
        comments: (each) => each.comments,
        withComments: (_, comments) => ({ comments }),
        change,
        inserting: setInserting,
        epoch,
        shownNow: true,
        tree,
        list: () => setListing(true),
        pending: setChord,
    });
    const before = useRef<Laid | null>(null);
    // Whether the message being begun was begun from the conversation's last line.
    const begunAtEnd = useRef(false);

    useEffect(() => {
        const view = editor.view.current;
        if (view === null || folded === null) {
            return;
        }
        const doc = view.state.doc.toString();
        const arriving = editor.landing.current;
        const selection = view.state.selection.main;
        const head = selection.head;
        // Where the reader is, by what was laid out before: following the end, or anywhere else.
        const where = before.current === null ? "last" : reading(before.current, head);
        const following = where !== "elsewhere" && (before.current === null || inSight(view, head));
        const made = changes(doc, laidOut.text);
        const changing = made.length > 0;
        let anchor: number | undefined;
        if (arriving !== null && "comment" in arriving) {
            anchor = laidOut.blocks.find((each) => each.comment === arriving.comment)?.from;
        } else if (arriving !== null && "at" in arriving) {
            anchor = moved(arriving.at, made, doc);
        } else if (changing && where === "last" && following) {
            anchor = laidOut.last?.from ?? 0;
        } else if (changing && selection.empty) {
            anchor = moved(head, made, doc);
        }
        if (changing) {
            view.dispatch({
                changes: made,
                selection: anchor === undefined ? undefined : { anchor },
                scrollIntoView: anchor !== undefined && (following || arriving !== null),
                annotations: rebuilt.of(true),
            });
        } else if (anchor !== undefined) {
            view.dispatch({ selection: { anchor }, scrollIntoView: true });
        }
        refold(view, folding, editor.kept.current);
        before.current = laidOut;
        editor.landing.current = null;
        editor.draw(decorations(laidOut, talk));
        if (arriving !== null && "comment" in arriving) {
            editor.enter();
        }
        // The editor's own refs are stable; what changes is what's laid out.
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [laidOut, talk, folded]);

    editor.bind({
        whole: (position) => {
            begunAtEnd.current = reading(laidOut, position) === "last";
            return { step: null, quote: null, text: "" };
        },
        opened: (position) => opened(laidOut, position),
        quoted: (from, to) => quoted(laidOut, from, to),
        about: (comment, _, opener) => {
            if (comment.step !== null) {
                return aboutAt(laidOut, comment);
            }
            // The message goes back to where the reader was when they began it: the end, where they were there.
            if (opener === null) {
                return laidOut.message?.from;
            }
            return begunAtEnd.current ? (laidOut.last?.from ?? 0) : Math.min(opener, laidOut.text.length);
        },
        move: (forward) => {
            const view = editor.view.current;
            if (view === null) {
                return;
            }
            const head = editor.head();
            const hidden = (position: number) => {
                let inside = false;
                foldedRanges(view.state).between(position, position, (from, to) => {
                    inside ||= position > from && position <= to;
                });
                return inside;
            };
            const turns = laidOut.turns.filter((each) => !hidden(each));
            const target = forward ? turns.find((each) => each > head) : [...turns].reverse().find((each) => each < head);
            if (target !== undefined) {
                view.dispatch({ selection: { anchor: target }, scrollIntoView: true });
            }
        },
        send: () => {
            if (saying(talk.comments).length > 0) {
                void sendNow();
            }
        },
        back,
    });

    async function sendNow() {
        const text = message(talk);
        // Everything the conversation has said before it's sent, so the message shows after it.
        await refresh();
        const after = have.current;
        try {
            const answer = await ask({ kind: "inbox-send", launch: launch.launch.launch, ...sending(talk), agent: subagent });
            if (answer.kind === "refused") {
                say(answer.error);
                return;
            }
            const number = answer.kind === "inbox-item" ? answer.item.number : 0;
            store({ talk: UNSAID, sent: [...current.current.sent, { number, text, after, at: new Date().toISOString() }] }, true);
            setEpoch((was) => was + 1);
            say(`Sent to ${talker.path} as #${number}, through lup.`);
        } catch (error) {
            say(error instanceof Error ? error.message : String(error));
        }
    }

    const saidComments = saying(talk.comments);
    const onWords = saidComments.filter((each) => each.step !== null).length;
    const whole = saidComments.length - onWords;
    const what = [
        onWords === 0 ? null : `${onWords} ${onWords === 1 ? "comment" : "comments"}`,
        whole === 0 ? null : "your message",
    ].filter((each) => each !== null);
    const kind = talker.agent == null ? "session" : (talker.kind ?? "subagent");
    return (
        <>
            <div className="wb">
                <button type="button" className="crumb" onClick={back} title="Back to the review (Space r)">
                    waiting on you <span className="count">{waiting}</span>
                </button>
                <span className="muted">›</span>
                <span>{talker.path}</span>
                <span className="count">
                    {kind} · {runtime} · {entries.length} {entries.length === 1 ? "step" : "steps"}
                </span>
            </div>
            <div className="review">
                <div className="buffer conversation-buffer" ref={editor.parent} />
                <div className="status">
                    {refused !== null ? (
                        <span className="error">Its record can't be read: {refused}</span>
                    ) : folded === null ? (
                        <span className="muted">Reading its record…</span>
                    ) : what.length === 0 ? (
                        <span className="muted">Nothing written to {talker.path}.</span>
                    ) : (
                        <span>
                            To {talker.path}: {what.join(" and ")}. <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends them as
                            one message.
                        </span>
                    )}
                    {sent.length === 0 ? null : (
                        <span className="muted"> Sent from here: {sent.map((each) => `#${each.number}`).join(", ")}.</span>
                    )}
                </div>
                <Keys
                    parts={CONVERSATION_KEYS}
                    place={inserting ? "insert" : "normal"}
                    places={CONVERSATION_PLACES}
                    open={listing}
                    setOpen={setListing}
                    pending={chord}
                />
            </div>
        </>
    );
}
