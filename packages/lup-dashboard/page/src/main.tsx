// The page's entry: trade the token in the address for the cookie, then show the dashboard.
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { session } from "./api";
import { App } from "./App";
import "./theme.css";

const root = document.getElementById("root");
if (root === null) {
    throw new Error("the page has no #root to show the dashboard in");
}
// A token refused here is said on the page, once its first watch is refused too.
await session(window.location, window.history).catch((error: unknown) => {
    console.warn("lup's dashboard: the token in the address was refused", error);
});
createRoot(root).render(
    <StrictMode>
        <App />
    </StrictMode>,
);
