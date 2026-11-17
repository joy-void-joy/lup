// The page: the server's socket, and the shell on the document's root view once the server names it.

import { look, Shell } from "./shell/shell";
import { bindVim, vimBindings } from "./shell/keymap";
import { margin, placeholder } from "./shell/margin";
import { painted } from "./shell/palette";
import { Server } from "./server";
import "./theme.css";

painted(document.documentElement);
const parent = document.getElementById("root");
const token = location.hash.slice(1) || sessionStorage.getItem("lup-token") || "";
sessionStorage.setItem("lup-token", token);
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
        const shell = new Shell(parent, opened.root, opened.looks, server, [look, margin(), placeholder]);
        shell.view.focus();
    },
    (refused) => {
        said.textContent = refused.reason;
    },
);
