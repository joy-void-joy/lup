// The draft reply beside the review: what it covers and who it reaches, each
// comment with a way to drop it, the verdicts given, and what's done or later.
import { Button } from "react-aria-components";

import { covered, type Draft, type Item } from "./review";

interface Props {
    draft: Draft;
    change: (draft: Draft) => void;
    items: Item[];
    name: (item: Item) => string;
}

/** The conversations a draft reaches: the sender of each item it covers, once each, in order. */
export function reached(draft: Draft, items: Item[], name: (item: Item) => string): string[] {
    const numbers = covered(draft);
    const senders = items.filter((each) => numbers.includes(each.number)).map(name);
    return [...new Set(senders)];
}

export function DraftPanel({ draft, change, items, name }: Props) {
    const numbers = covered(draft);
    const comments = draft.comments ?? [];
    const verdicts = draft.verdicts ?? [];
    const to = reached(draft, items, name);
    function dropped(at: number) {
        change({ ...draft, comments: comments.filter((_, each) => each !== at) });
    }
    return (
        <section className="draft" aria-label="Your reply">
            {numbers.length === 0 && comments.length === 0 ? (
                <p className="muted">
                    Nothing drafted yet. Select a passage with <kbd>v</kbd> and a motion, then <kbd>c</kbd>.
                </p>
            ) : (
                <p>
                    Covers {numbers.map((each) => `#${each}`).join(", ") || "nothing yet"}
                    {to.length === 0 ? "" : `, to ${to.join(", ")}`}.
                </p>
            )}
            <ol className="comments">
                {comments.map((comment, at) => (
                    <li key={`${comment.item ?? "whole"}-${at}`}>
                        <div className="on">
                            {comment.item == null
                                ? "on the whole"
                                : comment.quote == null
                                  ? `on #${comment.item}`
                                  : `on “${comment.quote.text}” in #${comment.item}`}
                        </div>
                        <div className="said">{comment.text}</div>
                        <Button className="drop" onPress={() => dropped(at)} aria-label="Drop this comment">
                            drop
                        </Button>
                    </li>
                ))}
            </ol>
            {verdicts.length === 0 ? null : (
                <ul className="verdicts">
                    {verdicts.map((each) => (
                        <li key={`${each.item}-${each.decision}`}>
                            #{each.item} decision {each.decision}: {each.verdict}
                        </li>
                    ))}
                </ul>
            )}
            {(draft.done ?? []).length === 0 ? null : (
                <p className="muted">Done: {(draft.done ?? []).map((each) => `#${each}`).join(", ")}</p>
            )}
            {(draft.parked ?? []).length === 0 ? null : (
                <p className="muted">Later: {(draft.parked ?? []).map((each) => `#${each}`).join(", ")}</p>
            )}
            <p className="muted">
                <kbd>Ctrl</kbd> <kbd>Enter</kbd> sends it.
            </p>
        </section>
    );
}
