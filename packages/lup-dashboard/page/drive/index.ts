// The room's Chromium driving the dashboard (`docs/dashboard.md`, *The demo*): what a session imports from its own
// script, run with Node, which runs TypeScript as it is.
//
//     import { demo, open, timed } from "../packages/lup-dashboard/page/drive/index.ts";
//
//     await using served = await demo({ approvalLines: 30000 });
//     await using dashboard = await open(served.url);
//     const review = await dashboard.review();
//     await review.goTo("── @66 note");
//     await review.comment();
//     const keys = await timed(dashboard.page, () => dashboard.keys.type("hello", 120));
//
// `open(url, { windowed: US_INTERNATIONAL })` gives the page a window on a virtual display of its own, whose
// `dashboard.display.press(["dead_acute", "e"])` types as that keyboard does. `typing.ts` is the measure every session
// working on the review's speed takes, as a command.
export { demo, type Demo, type DemoOptions } from "./demo.ts";
export { open, type Dashboard, type OpenOptions } from "./dashboard.ts";
export { US_INTERNATIONAL, type Display, type Layout } from "./display.ts";
export { events, type KeyEvent, type Keys, type Sent } from "./keys.ts";
export { type Mode, type Review } from "./review.ts";
export { percentiles, timed, type KeyTime, type Percentiles, type Timed } from "./timing.ts";
export { DEMO_ITEM, typing, type Typing, type TypingOptions } from "./typing.ts";
