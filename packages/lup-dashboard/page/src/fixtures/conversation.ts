// An agent's conversation as `Transcripts` answers its views (`conversation.json`, which the dashboard's Python tests
// hold to the module's own layout): what the page's tests lay out as the agent's drawer, as the host keeps its answers
// for the page (`Remote`), the drawer's and its earlier exchange's, read as its fold opens.
import { instanceOf, type Blocks, type Remote } from "../views";
import transcribed from "./conversation.json";

/** The repository the conversation is of. */
export const REPOSITORY = transcribed.repository;

/** Each view's answer, by its instance's id: the drawer, `conversation`, and its earlier exchange, `exchange`. */
export const ANSWERED: Remote = new Map(
    transcribed.answers.map((each) => [instanceOf(REPOSITORY, "transcripts", each.view, each.argument), each.answer as unknown as Blocks]),
);

/** The drawer's answer alone, its earlier exchange not read yet. */
export const DRAWER_ONLY: Remote = new Map([...ANSWERED].filter(([id]) => id.includes('"conversation"')));
