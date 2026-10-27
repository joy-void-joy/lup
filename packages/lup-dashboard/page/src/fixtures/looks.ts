// The looks of lup's default declaration, as `resolve(Project()).looks` gives them (`looks.json`, which the dashboard's
// Python tests hold to it): what the page's tests lay the review out by, adopted as this module is imported, so they
// read the same fold kinds, drawers and tones the host's listing gives the page.
import { adopt, merged, type Looks, type Merged } from "../looks";
import declared from "./looks.json";

/** lup's default declaration's looks, as the listing's `standing` gives them. */
export const STANDING = declared as unknown as Looks;

/** Those looks, merged, as the page merges them where every repository's process has yet to say its own. */
export const LOOKS: Merged = merged({}, STANDING);

adopt(LOOKS);
