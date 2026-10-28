// `Transcripts`' conversation, as the page lays it out until the drawer is `Transcripts`' own view of it (#113, step
// 3b's fourth branch; `views.ts`): its summary line counting its steps, and its text, laid out by the page's
// `conversation.ts` from the record as read so far, the items it exchanged and each call read whole, with the
// operator's remarks on it. The module's own view (`lup_transcripts.environment.conversation`) answers the same drawer
// in blocks once it's mounted from the host. Pure.
import { UNEXCHANGED, laid } from "../conversation";
import { conversationOf, whose, type OfAgent, type View } from "../views";

/** Say how many of a thing there are: `1 step`, `5 steps`. */
function counted(count: number, one: string): string {
    return `${count} ${one}${count === 1 ? "" : "s"}`;
}

/** The agent's conversation: `conversation · 33 steps` under its banner, its text laid out with the remarks on it; none before its record is read. */
export const CONVERSATION: View<OfAgent> = {
    module: "transcripts",
    view: "conversation",
    answer: (of, shown, repository) => {
        const conversation = conversationOf(repository, of);
        const data = shown.drawers.get(whose(conversation));
        if (data === undefined || data.entries.length === 0) {
            return null;
        }
        const beside = { exchanged: data.exchanged ?? UNEXCHANGED, whose: { agent: of.agent ?? null, name: shown.called }, calls: data.calls };
        return {
            blocks: { summary: [{ text: `conversation · ${counted(data.entries.length, "step")}`, tone: "plain" }], waiting: false, count: 0, offers: [], blocks: [] },
            talk: (remarks) => laid(data.entries, beside, { comments: remarks }),
        };
    },
};
