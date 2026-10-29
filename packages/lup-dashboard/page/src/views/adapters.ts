// The runtime adapters' views, which the page lays out until the adapters are a module (#113, step 4; `views.ts`): an
// agent's task list, as their runtime keeps it, a drawer under their banner, each entry marked done, in progress or to
// do; and the adapters' part of the agent's banner, the current entry of their task list and their context's ring, the
// tokens in use against their model's window (`◔ 112k/1M`). Each from what the page last read of the agent's record. Pure.
import { ring } from "../agents";
import type { components } from "../generated/api";
import { conversationOf, whose, type Line, type OfAgent, type Span, type View } from "../views";

type Task = components["schemas"]["Task"];

/** The marks before a task, by its status: done, in progress, to do. */
const TASK_MARKS = { completed: "✓", in_progress: "▶", pending: "·" } as const;

/** Return the current entry of a task list: the one in progress, what it says while in progress, else the first to do; none where there's neither. */
export function currentTask(tasks: Task[]): string | null {
    const going = tasks.find((each) => each.status === "in_progress");
    if (going !== undefined) {
        return going.active ?? going.subject;
    }
    return tasks.find((each) => each.status === "pending")?.subject ?? null;
}

/** The agent's task list: `tasks 1/3` under their banner, each entry a line, what it says while in progress for the one in progress; none where their runtime keeps no list. */
export const TASKS: View<OfAgent> = {
    module: "adapters",
    view: "tasks",
    answer: (of, shown, repository) => {
        const tasks = shown.drawers.get(whose(conversationOf(repository, of)))?.tasks ?? [];
        if (tasks.length === 0) {
            return null;
        }
        const done = tasks.filter((each) => each.status === "completed").length;
        const lines = tasks.map((task): Line => {
            const said = task.status === "in_progress" ? (task.active ?? task.subject) : task.subject;
            return { block: "line", id: `task ${task.id}`, version: null, offers: [], spans: [{ text: `${TASK_MARKS[task.status]} ${said}`, tone: "task" }] };
        });
        return { blocks: { summary: [{ text: `tasks ${done}/${tasks.length}`, tone: "plain" }], waiting: false, count: 0, offers: [], blocks: lines } };
    },
};

/** The adapters' part of an agent's banner: `▶` their current task, then their context's ring, measured; none of either the record hasn't said. */
export const BANNER: View<OfAgent> = {
    module: "adapters",
    view: "banner",
    answer: (of, shown, repository) => {
        const data = shown.drawers.get(whose(conversationOf(repository, of)));
        if (data === undefined) {
            return null;
        }
        const task = currentTask(data.tasks);
        const usage = data.usage;
        const parts: Span[][] = [
            ...(task === null ? [] : [[{ text: `▶ ${task}`, tone: "plain" }]]),
            ...(usage === null ? [] : [[{ text: ring(usage.used, usage.window), tone: "plain", gauge: { used: usage.used, of: usage.window ?? null } }]]),
        ];
        const summary = parts.flatMap((each, at) => (at === 0 ? each : [{ text: " · ", tone: "plain" }, ...each]));
        return { blocks: { summary, waiting: false, count: 0, offers: [], blocks: [] } };
    },
};
