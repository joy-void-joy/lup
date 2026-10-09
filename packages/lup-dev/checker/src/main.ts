// lup's typed engine (`docs/judging-writes.md`, *The engine: one typed tree*).
//
//   start --root R --socket S --idle-seconds N --log L
//       Make sure an engine serves the worktree R on socket S: return at once if one
//       answers there, otherwise start one detached, logging to L, and return once it
//       listens. Hooks run this; the engine outlives them.
//   serve --root R --socket S --idle-seconds N
//       Be that engine, in the foreground.
//   rules
//       Print lup's rules (id, mistake, steer, examples) as JSON.
//
// The engine's build is identified by its bundle's size and modification time,
// which the client reads from the same file.

import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as net from 'net';
import * as path from 'path';

import { initializeDependencies } from 'pyright/common/asyncInitialization';

import { ruleInfos } from './catalog';
import { Engine } from './engine';
import { Server, ServeOptions } from './server';

interface Arguments {
    command: string;
    root: string;
    socket: string;
    idleSeconds: number;
    log: string;
}

function parse(argv: string[]): Arguments {
    const [command, ...rest] = argv;
    const named = new Map<string, string>();
    for (let index = 0; index < rest.length; index += 2) {
        if (!rest[index].startsWith('--') || rest[index + 1] === undefined) {
            throw new Error(`expected \`--name value\` pairs, not ${JSON.stringify(rest.slice(index))}`);
        }
        named.set(rest[index].substring(2), rest[index + 1]);
    }
    const need = (name: string) => {
        const value = named.get(name);
        if (value === undefined) {
            throw new Error(`\`${command}\` needs --${name}`);
        }
        return value;
    };
    return {
        command,
        root: command === 'rules' ? '' : path.resolve(need('root')),
        socket: command === 'rules' ? '' : need('socket'),
        idleSeconds: command === 'rules' ? 0 : Number(need('idle-seconds')),
        log: command === 'start' ? need('log') : '',
    };
}

function build(): string {
    const stat = fs.statSync(__filename, { bigint: true });
    return `${stat.size}-${stat.mtimeNs}`;
}

// Whether an engine answers on the socket.
function answers(socket: string): Promise<boolean> {
    return new Promise((resolve) => {
        const connection = net.connect(socket);
        connection.once('connect', () => {
            connection.end();
            resolve(true);
        });
        connection.once('error', () => resolve(false));
    });
}

async function start(args: Arguments) {
    if (await answers(args.socket)) {
        return;
    }
    fs.mkdirSync(path.dirname(args.socket), { recursive: true, mode: 0o700 });
    fs.mkdirSync(path.dirname(args.log), { recursive: true });
    const log = fs.openSync(args.log, 'a');
    const engine: ChildProcess = spawn(
        process.execPath,
        [
            __filename,
            'serve',
            '--root',
            args.root,
            '--socket',
            args.socket,
            '--idle-seconds',
            String(args.idleSeconds),
        ],
        { detached: true, stdio: ['ignore', 'ignore', log, 'ipc'] }
    );
    const outcome = await new Promise<string>((resolve) => {
        engine.once('message', (message) => resolve(String(message)));
        engine.once('exit', (code) => resolve(`the engine exited with ${code} before it listened; see ${args.log}`));
    });
    if (outcome !== 'ready') {
        throw new Error(outcome);
    }
    engine.disconnect();
    engine.unref();
}

async function serve(args: Arguments) {
    const options: ServeOptions = {
        root: args.root,
        socket: args.socket,
        idleSeconds: args.idleSeconds,
        build: build(),
    };
    try {
        const server = new Server(new Engine(args.root), options);
        await server.listen();
        process.send?.('ready');
    } catch (error) {
        process.send?.(`the engine failed to start: ${error instanceof Error ? error.message : String(error)}`);
        throw error;
    }
}

async function main() {
    const args = parse(process.argv.slice(2));
    // pyright loads its TOML parser asynchronously, before any configuration is read.
    await initializeDependencies();
    // pyright finds its standard-library stubs through this global, beside the bundle.
    (global as { __rootDirectory?: string }).__rootDirectory = path.dirname(__filename);
    switch (args.command) {
        case 'start':
            await start(args);
            return;
        case 'serve':
            await serve(args);
            return;
        case 'rules':
            process.stdout.write(JSON.stringify(ruleInfos()) + '\n');
            return;
        default:
            throw new Error(`no command named ${JSON.stringify(args.command)}: it's start, serve or rules`);
    }
}

main().catch((error) => {
    process.stderr.write((error instanceof Error ? error.stack ?? error.message : String(error)) + '\n');
    process.exit(1);
});
