// The page: the server's socket, and the shell on the document's root view once the server names it.

import { look, overview, Shell } from "./shell/shell";
import { bindVim, vimBindings } from "./shell/keymap";
import { margin, placeholder } from "./shell/margin";
import { painted } from "./shell/palette";
import { remembered, Server } from "./server";
import "./theme.css";

painted(document.documentElement);
const parent = document.getElementById("root");
const token = remembered(location.hash, localStorage);
history.replaceState(null, "", location.pathname);
bindVim(vimBindings);

const said = document.createElement("div");
said.className = "lup-said";
parent?.append(said);

const server: Server = new Server(
    `${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/api/socket`,
    token,
    (opened) => {
        if (opened.root === null || parent === null) {
            said.textContent = "The home repository's declaration names no document.";
            return;
        }
        const element = (tag: string, className: string, ...children: HTMLElement[]): HTMLElement => {
            const made = document.createElement(tag);
            made.className = className;
            made.append(...children);
            return made;
        };
        const title = element("div", "lup-pane-title");
        title.textContent = "outline";
        const aside = element("div", "lup-outline");
        const header = element("div", "lup-where");
        const main = element("div", "lup-main");
        const keys = element("div", "lup-keys");
        const page = element(
            "div",
            "lup-page",
            element("div", "lup-pane lup-outline-pane", title, aside),
            element("div", "lup-pane lup-document-pane", header, main, keys),
        );
        parent.append(page);
        const shell = new Shell(main, opened.root, opened.looks, server, {
            extensions: [look, margin(), placeholder],
            outlining: [look, overview],
            aside,
            page,
            header,
            keys,
        });
        shell.view.focus();
        shell.reframe();
    },
    (refused) => {
        said.textContent = refused.reason;
    },
    (why) => {
        said.textContent = why;
    },
);
