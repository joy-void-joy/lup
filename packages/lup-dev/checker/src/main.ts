// lup's typed engine (`docs/judging-writes.md`, *The engine: one typed tree*).
//
//   start --root R --socket S --idle-seconds N --interpreter I --environment-files F --log L
//       Make sure an engine serves the worktree R on socket S: return at once if one
//       answers there, otherwise start one detached, logging to L, and return once it
//       listens. Hooks run this; the engine outlives them.
//   serve --root R --socket S --idle-seconds N --interpreter I --environment-files F
//       Be that engine, in the foreground.
//   rules
//       Print lup's rules (id, mistake, steer, examples) as JSON: every rule of the
//       table, or, given each module's rule selection on its input (a JSON list of
//       `Selected`, as a check request carries them), the rules their union runs,
//       resolved as a check resolves them. Nothing on its input, or a terminal,
//       gives the table.
//   parse
//       Read files from their parse alone, with no project loaded (`parsed.ts`): a
//       JSON list of `{path, content}` on its input, and each file's report printed
//       as JSON, in the same order.
//
// I and F are JSON lists of strings, from the project's runner: the command running
// the worktree's Python, which the engine runs to name its interpreter, and the
// files, from the root, whose change means another environment.
//
// The engine's build is identified by its bundle's size and modification time,
// which the client reads from the same file.

import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as net from 'net';
import * as path from 'path';

import { initializeDependencies } from 'pyright/common/asyncInitialization';

import { ruleInfos, SelectionError } from './catalog';
import { Engine } from './engine';
import { parsedReport } from './parsed';
import { Environment, ParsedSource, Selected, Selection } from './protocol';
import { Server, ServeOptions } from './server';

interface Arguments {
    command: string;
    root: string;
    socket: string;
    idleSeconds: number;
    environment: Environment;
    log: string;
}

// A JSON list of strings, as the client passes the runner's command and files.
function strings(name: string, text: string): string[] {
    const refused = () => new Error(`--${name} takes a JSON list of strings, not ${JSON.stringify(text)}`);
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw refused();
    }
    if (!Array.isArray(parsed) || !parsed.every((each) => typeof each === 'string')) {
        throw refused();
    }
    return parsed as string[];
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
    const listed = (name: string) => strings(name, need(name));
    // `rules` and `parse` load no project, so they take nothing.
    const alone = command === 'rules' || command === 'parse';
    return {
        command,
        root: alone ? '' : path.resolve(need('root')),
        socket: alone ? '' : need('socket'),
        idleSeconds: alone ? 0 : Number(need('idle-seconds')),
        environment: alone
            ? { interpreter: [], files: [] }
            : { interpreter: listed('interpreter'), files: listed('environment-files') },
        log: command === 'start' ? need('log') : '',
    };
}

// The files `parse` reads, as its input gives them.
function sources(text: string): ParsedSource[] {
    const refused = () => new Error('`parse` reads a JSON list of `{"path": …, "content": …}` strings on its input');
    let given: unknown;
    try {
        given = JSON.parse(text);
    } catch {
        throw refused();
    }
    const isSource = (each: unknown): each is ParsedSource =>
        typeof each === 'object' &&
        each !== null &&
        typeof (each as ParsedSource).path === 'string' &&
        typeof (each as ParsedSource).content === 'string';
    if (!Array.isArray(given) || !given.every(isSource)) {
        throw refused();
    }
    return given;
}

// The rule selections `rules` resolves, as its input gives them: none where it's
// given nothing, so it lists the table.
function selections(text: string): Selected[] | undefined {
    if (!text.trim()) {
        return undefined;
    }
    const refused = () =>
        new Error(
            '`rules` reads nothing, or a JSON list of `{"module": …, "rules": …, "default": …}` rule selections, on its input'
        );
    let given: unknown;
    try {
        given = JSON.parse(text);
    } catch {
        throw refused();
    }
    const isSelection = (each: unknown): each is Selection =>
        typeof each === 'object' &&
        each !== null &&
        typeof (each as Selection).start === 'object' &&
        (each as Selection).start !== null &&
        Array.isArray((each as Selection).operations);
    const isSelected = (each: unknown): each is Selected =>
        typeof each === 'object' &&
        each !== null &&
        typeof (each as Selected).module === 'string' &&
        isSelection((each as Selected).rules) &&
        isSelection((each as Selected).default);
    if (!Array.isArray(given) || !given.every(isSelected)) {
        throw refused();
    }
    return given;
}

// What the command was given on its input; nothing where its input is a terminal,
// which would otherwise wait for it.
function input(): string {
    return process.stdin.isTTY ? '' : fs.readFileSync(0, 'utf8');
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
            '--interpreter',
            JSON.stringify(args.environment.interpreter),
            '--environment-files',
            JSON.stringify(args.environment.files),
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
        environment: args.environment,
    };
    try {
        const server = new Server(new Engine(args.root, args.environment), options);
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
            process.stdout.write(JSON.stringify(ruleInfos(selections(input()))) + '\n');
            return;
        case 'parse':
            process.stdout.write(JSON.stringify(sources(fs.readFileSync(0, 'utf8')).map(parsedReport)) + '\n');
            return;
        default:
            throw new Error(`no command named ${JSON.stringify(args.command)}: it's start, serve, rules or parse`);
    }
}

// A selection the table can't resolve is said as the declaration's errors are, without
// a stack, as the server says it; any other failure with its stack.
main().catch((error) => {
    const said =
        error instanceof SelectionError || !(error instanceof Error)
            ? String(error instanceof Error ? error.message : error)
            : error.stack ?? error.message;
    process.stderr.write(said + '\n');
    process.exit(1);
});
