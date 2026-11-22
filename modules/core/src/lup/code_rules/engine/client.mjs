// Ask lup's engine kept running for a worktree one thing, on its socket: the request,
// one JSON line, on this program's input, and the engine's answer, one JSON line,
// printed. Its client runs it through `node`, a program lup stands in for where a
// promise checks what's told after a write (`lup/code_rules/engine.py`, `WarmEngine`).

import * as net from 'node:net';

const [socket] = process.argv.slice(2);
let asked = '';
process.stdin.setEncoding('utf8');
process.stdin.on('data', (chunk) => {
    asked += chunk;
});
process.stdin.on('end', () => {
    const connection = net.connect(socket);
    let said = '';
    connection.setEncoding('utf8');
    connection.on('data', (chunk) => {
        said += chunk;
        const end = said.indexOf('\n');
        if (end >= 0) {
            process.stdout.write(said.slice(0, end + 1));
            connection.end();
        }
    });
    connection.on('error', (error) => {
        process.stderr.write(`the engine's socket, ${socket}: ${error.message}\n`);
        process.exit(1);
    });
    connection.write(asked.trim() + '\n');
});
