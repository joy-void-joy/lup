// The core's views of its own party's items, lup's approvals (#113, step 4; `views.ts`): an approval of a repository's
// copy, its summary what it is and how its files read, its body its question and the summary of what changed, then
// each file it changes, whole, each of a first approval folded under its header, since a first approval trusts the
// repository as it is; approving or declining it, Space d and Space x, as the reply is sent. Pure.
import { answering, changed, type OfItem } from "./judge";
import type { View } from "../views";

/** Return `text` without the terminal's colour codes git colours a diff with. */
export function plain(text: string): string {
    return text.replace(/\u001b\[[0-9;]*m/g, "");
}

/** An approval of a repository's copy: what it asks, the summary of what changed without git's colours, and each file. */
export const APPROVAL: View<OfItem> = {
    module: "core",
    view: "approval",
    answer: ({ number }, shown) => {
        const item = shown.items.get(number);
        if (item?.reason.reason !== "approval") {
            return null;
        }
        const reason = item.reason;
        // An approval commented on stays unanswered, its comments going to the session that pushed: a comment implies nothing.
        return changed(item, "approval", `${reason.text}\n${plain(reason.summary)}`, shown, reason.first, answering(item, false));
    },
};
