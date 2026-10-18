// One agent's conversation, opened from the tree: the whole of it from its start
// in one buffer moved through with vim (`editor.ts`), what came before the
// operator's last words folded, growing as the agent works. Their comments are
// written into it under the agent's lines, `c` writing their message on the
// whole, and Ctrl+Enter sends them to the conversation as one message, through
// lup. As it grows, the view follows only a reader on its last line, or writing
// their message at its end; anyone else keeps their cursor, what they see, their
// open folds and what they're writing. Space `r` brings the review back
// (`docs/dashboard.md`, *The conversation*).
import { foldEffect, foldedRanges, unfoldEffect } from "@codemirror/language";
import { RangeSetBuilder, type StateEffect } from "@codemirror/state";
import { Decoration, type DecorationSet, type EditorView } from "@codemirror/view";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import type { Agent, Launch } from "./agents";
import { ask } from "./api";
import { saying, shownIn, type Folding, type Span } from "./comments";
import {
    UNSAID,
    aboutAt,
    changes,
    history,
    laid,
    message,
    moved,
    opened,
    quoted,
    reading,
    type Entry,
    type Laid,
    type Remark,
    type Sent,
    type Talk,
} from "./conversation";
import { rebuilt, useEditor } from "./editor";

interface Props {
    launch: Launch;
    agent: Agent;
    /** Changes at every hook the host hears: the conversation is asked again for what it has since. */
    beat: unknown;
    /** How many items wait in the operator's inbox, said where the review is gone back to. */
    waiting: number;
    /** Bring the review back. */
    back: () => void;
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

/** Each conversation's draft and messages sent, kept in the page as they're written, and in its storage, so a reload keeps them. */
const kept = new Map<string, Kept>();

function keyOf(runtime: string, session: string, agent: string | null): string {
    return `lup-dashboard.conversation:${runtime}:${session}:${agent ?? ""}`;
}

function load(key: string): Kept {
    const held = kept.get(key);
    if (held !== undefined) {
        return held;
    }
    try {
        const stored = localStorage.getItem(key);
        if (stored !== null) {
            const read = JSON.parse(stored) as Partial<Kept>;
            return { talk: { comments: read.talk?.comments ?? [] }, sent: read.sent ?? [] };
        }
    } catch (error) {
        console.warn("lup's dashboard: a conversation's draft couldn't be read back", error);
    }
    return { talk: UNSAID, sent: [] };
}

function keep(key: string, value: Kept): void {
    kept.set(key, value);
    try {
        localStorage.setItem(key, JSON.stringify(value));
    } catch (error) {
        console.warn("lup's dashboard: a conversation's draft couldn't be kept", error);
    }
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

/** Fold what folds again as the operator left it, where the text around it changed: folded unless they opened it. */
function refold(view: EditorView, fold: Folding | null, unfolded: Set<string>): void {
    if (fold === null) {
        return;
    }
    const effects: StateEffect<Span>[] = [];
    let exact = false;
    foldedRanges(view.state).between(fold.from, fold.to, (from, to) => {
        if (from === fold.from && to === fold.to) {
            exact = true;
        } else if (from === fold.from) {
            effects.push(unfoldEffect.of({ from, to }));
        }
    });
    const closing = !unfolded.has(fold.key);
    if (closing && !exact) {
        effects.push(foldEffect.of({ from: fold.from, to: fold.to }));
    }
    if (!closing && exact) {
        effects.push(unfoldEffect.of({ from: fold.from, to: fold.to }));
    }
    if (effects.length > 0) {
        view.dispatch({ effects });
    }
}

const NOTHING: Laid = { text: "", words: [], asides: [], blocks: [], fold: null, turns: [], last: null, message: null };

export function Conversation({ launch, agent, beat, waiting, back, say }: Props) {
    const { talker } = agent;
    const runtime = launch.launch.runtime;
    const subagent = talker.agent ?? null;
    const key = keyOf(runtime, talker.session, subagent);
    const [{ talk, sent }, setKept] = useState<Kept>(() => load(key));
    const [entries, setEntries] = useState<Entry[]>([]);
    // How many turns are folded, once the conversation is first read: before the operator's last words then.
    const [folded, setFolded] = useState<number | null>(null);
    const [refused, setRefused] = useState<string | null>(null);
    const [confirming, setConfirming] = useState(false);
    const [inserting, setInserting] = useState(false);
    const [epoch, setEpoch] = useState(0);
    const have = useRef(0);
    const asking = useRef(false);
    const again = useRef(false);
    const sentNow = useRef(sent);
    sentNow.current = sent;

    const change = useCallback(
        (next: Talk) => {
            setKept((before) => {
                const after = { ...before, talk: next };
                keep(key, after);
                return after;
            });
        },
        [key],
    );

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
                    setFolded((before) => before ?? 0);
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

    const laidOut = useMemo(
        () => (folded === null ? NOTHING : laid(entries, sent, talk, folded)),
        [entries, sent, talk, folded],
    );
    const editor = useEditor<Talk, Remark>({
        shown: { text: laidOut.text, blocks: laidOut.blocks, folds: laidOut.fold === null ? [] : [laidOut.fold] },
        draft: talk,
        comments: (each) => each.comments,
        withComments: (_, comments) => ({ comments }),
        change,
        inserting: setInserting,
        epoch,
        confirming,
        shownNow: true,
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
        } else if (changing && where === "last" && following) {
            anchor = laidOut.last?.from ?? 0;
        } else if (changing && selection.empty) {
            anchor = moved(head, made, doc.length);
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
        refold(view, laidOut.fold, editor.unfolded.current);
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
        send: () => setConfirming(saying(talk.comments).length > 0),
        back,
    });

    async function sendNow() {
        setConfirming(false);
        const text = message(talk);
        // Everything the conversation has said before it's sent, so the message shows after it.
        await refresh();
        const after = have.current;
        try {
            const answer = await ask({ kind: "inbox-send", launch: launch.launch.launch, text, agent: subagent });
            if (answer.kind === "refused") {
                say(answer.error);
                return;
            }
            const number = answer.kind === "inbox-item" ? answer.item.number : 0;
            setKept((was) => {
                const next = {
                    talk: UNSAID,
                    sent: [...was.sent, { number, text, after, at: new Date().toISOString() }],
                };
                keep(key, next);
                return next;
            });
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
                {inserting ? (
                    <div className="keys inserting">
                        -- INSERT -- writing a comment · <kbd>Ctrl</kbd> <kbd>Enter</kbd> ends it, back on what it's
                        about · <kbd>Esc</kbd> ends it here · <kbd>Esc</kbd> <kbd>u</kbd> drops it
                    </div>
                ) : (
                    <div className="keys muted">
                        comment: <kbd>o</kbd>/<kbd>C</kbd> line · <kbd>v</kbd>…<kbd>c</kbd> selection · <kbd>c</kbd>{" "}
                        message · <kbd>u</kbd>/<kbd>^r</kbd> undo/redo · <kbd>za</kbd> fold · <kbd>zR</kbd>/
                        <kbd>zM</kbd> unfold/fold all · <kbd>J</kbd>/<kbd>K</kbd> turns · <kbd>␣r</kbd> review
                    </div>
                )}
            </div>
            {confirming ? (
                <div
                    className="confirm"
                    role="dialog"
                    aria-label="Send your message"
                    tabIndex={-1}
                    ref={(box) => box?.focus()}
                    onKeyDown={(event) => {
                        if (event.key === "Enter") {
                            event.preventDefault();
                            void sendNow();
                        }
                        if (event.key === "Escape") {
                            setConfirming(false);
                        }
                    }}
                >
                    <p>Send {what.join(" and ")} to {talker.path}?</p>
                    <p className="muted">
                        As one message through lup, each comment under what it quotes
                        {whole === 0 ? "" : ", your message last"}: it reads it at its next call, or is woken.{" "}
                        <kbd>Enter</kbd> sends · <kbd>Esc</kbd> goes back.
                    </p>
                </div>
            ) : null}
        </>
    );
}
