// The views of the items the agent-facing inbox carries (#113, step 4; `views.ts`): a message, a turn's last words
// among them, a question with its decisions, a friction, how the work went, a stop by choice, a subagent's end, lup's
// word on citations that named no passage, and the operator's own answers and reviews, which the review shows above
// an agent's answer to them. Each a summary, what it is and, for a message between conversations, whom it went to; and
// a body, its text as written, a question's decisions numbered with their leans. Pure.
import type { components } from "../generated/api";
import type { Answer, Span, View } from "../views";
import type { OfItem } from "./judge";

type Item = components["schemas"]["Item"];

/** Say what an item is in its header: a message by its kind, or as a turn's end; a stop by choice; or the reason's own name. */
function what(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
            return reason.ending === true ? "turn ended" : reason.kind;
        case "stop":
            return "stopped";
        default:
            return reason.reason;
    }
}

/**
 * Return an item's own text as the review shows it: a message's, a friction's or how the work went's words as written,
 * a question's with its decisions; a subagent's end's last message, where lup passed it on; lup's word on citations,
 * what each said; an answer's comment; a review's messages and comments.
 */
export function body(item: Item): string {
    const reason = item.reason;
    switch (reason.reason) {
        case "message":
        case "friction":
        case "how it went":
            return reason.text;
        case "stop":
            return reason.why;
        case "ended":
            return reason.said ?? "";
        case "unresolved":
            return reason.citations.map((each) => each.said).join("\n");
        case "question": {
            const decisions = reason.decisions.map((each, at) => `${at + 1}. ${each.text}\n   lean: ${each.lean}`);
            return [reason.text, ...decisions].join("\n");
        }
        case "answer":
            return reason.comment;
        case "review":
            return [...(reason.letters ?? []), ...reason.comments].map((each) => each.text).join("\n");
        default:
            return "";
    }
}

/** Return the view of an agent-facing item of `reason`: its summary, what it is and, for a message between conversations, whom it went to, named by its path; its body, its text. */
function itemView(name: string, reason: Item["reason"]["reason"]): View<OfItem> {
    return {
        module: "inbox",
        view: name,
        answer: ({ number }, shown): Answer | null => {
            const item = shown.items.get(number);
            if (item === undefined || item.reason.reason !== reason) {
                return null;
            }
            const to = item.reason.reason === "message" ? (item.reason.to ?? null) : null;
            const summary: Span[] = [
                { text: what(item), tone: "plain" },
                ...(to === null
                    ? []
                    : [
                          { text: " to ", tone: "plain" },
                          { text: shown.called(to), tone: "plain", conversation: { runtime: to.runtime, session: to.session, agent: to.agent ?? null } },
                      ]),
            ];
            return {
                blocks: {
                    summary,
                    waiting: false,
                    count: 0,
                    offers: [],
                    blocks: [{ block: "markdown", id: "text", version: null, offers: [], text: body(item), tone: "plain" }],
                },
            };
        },
    };
}

export const MESSAGE = itemView("message", "message");
export const QUESTION = itemView("question", "question");
export const FRICTION = itemView("friction", "friction");
export const HOW_IT_WENT = itemView("how_it_went", "how it went");
export const STOP = itemView("stop", "stop");
export const ENDED = itemView("ended", "ended");
export const UNRESOLVED = itemView("unresolved", "unresolved");
export const ANSWER = itemView("answer", "answer");
export const REVIEW = itemView("review", "review");
