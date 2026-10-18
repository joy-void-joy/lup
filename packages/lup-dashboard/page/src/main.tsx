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
await session(window.location, window.history);
createRoot(root).render(
    <StrictMode>
        <App />
    </StrictMode>,
);
