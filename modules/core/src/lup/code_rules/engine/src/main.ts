// lup's typed engine: pyright's own program, with lup's rules reading its tree and
// types (`lup/code_rules/README.md`, *The engine*).
//
//   start --root R --socket S --idle-seconds N --venv V --environment-files F --log L
//       Make sure an engine serves the worktree R on socket S: return at once if one
//       answers there, otherwise start one detached, logging to L, and return once it
//       listens. Its client runs this; the engine outlives it.
//   serve --root R --socket S --idle-seconds N --venv V --environment-files F
//       Be that engine, in the foreground.
//   comments
//       Find TypeScript files' `// lup:` comments with TypeScript's own parser: a JSON
//       list of `{path, content}` on its input, and each file's comments printed as
//       JSON, in the same order.
//   check --root R --venv V --environment-files F
//       Check files once, with no engine left running: `{"rules": […], "sources":
//       […]}` on its input, as a check request carries them, and each file's report
//       printed as JSON, in the same order. What the gate and a check typed by hand
//       run, where one load of the project serves every file.
//   rules
//       Print every rule of the table (id, mistake, steer, category, examples) as
//       JSON.
//   parse
//       Read files from their parse alone, with no project loaded (`parsed.ts`): a
//       JSON list of `{path, content}` on its input, and each file's report printed
//       as JSON, in the same order.
//
// V and F are JSON: the directory of the worktree's virtual environment, which the
// engine reads as files, from the root or absolute, or null for none; and a list of
// the files, from the root, whose change means another environment.
//
// The engine's build is identified by its bundle's size and modification time,
// which the client reads from the same file.

import { ChildProcess, spawn } from 'child_process';
import * as fs from 'fs';
import * as net from 'net';
import * as path from 'path';

import { initializeDependencies } from 'pyright/common/asyncInitialization';

import { ruleInfos, UnknownRuleError } from './catalog';
import { Engine } from './engine';
import { parsedReport } from './parsed';
import { Environment, ParsedSource, SourceRequest } from './protocol';
import { Server, ServeOptions } from './server';
import { lupComments } from './typescript';

interface Arguments {
    command: string;
    root: string;
    socket: string;
    idleSeconds: number;
    environment: Environment;
    log: string;
}

// A JSON string, or null, as the client passes the runner's environment.
function stringOrNull(name: string, text: string): string | null {
    const refused = () => new Error(`--${name} takes a JSON string or null, not ${JSON.stringify(text)}`);
    let parsed: unknown;
    try {
        parsed = JSON.parse(text);
    } catch {
        throw refused();
    }
    if (parsed !== null && typeof parsed !== 'string') {
        throw refused();
    }
    return parsed;
}

// A JSON list of strings, as the client passes the runner's files.
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
    // `rules` and `parse` load no project, so they take nothing; `check` serves on
    // no socket.
    const alone = command === 'rules' || command === 'parse' || command === 'comments';
    const served = command === 'start' || command === 'serve';
    return {
        command,
        root: alone ? '' : path.resolve(need('root')),
        socket: served ? need('socket') : '',
        idleSeconds: served ? Number(need('idle-seconds')) : 0,
        environment: alone
            ? { venv: null, files: [] }
            : { venv: stringOrNull('venv', need('venv')), files: listed('environment-files') },
        log: command === 'start' ? need('log') : '',
    };
}

// The files `parse` reads, as its input gives them.
function sources(text: string): ParsedSource[] {
    const refused = () =>
        new Error('`parse` and `comments` read a JSON list of `{"path": …, "content": …}` strings on their input');
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

// What `check` checks, as its input gives it.
function checking(text: string): { rules: string[]; sources: SourceRequest[] } {
    const refused = () =>
        new Error('`check` reads `{"rules": [names…], "sources": [{"path": …, "content": … or null}…]}` on its input');
    let given: unknown;
    try {
        given = JSON.parse(text);
    } catch {
        throw refused();
    }
    const isSource = (each: unknown): each is SourceRequest =>
        typeof each === 'object' &&
        each !== null &&
        typeof (each as SourceRequest).path === 'string' &&
        ((each as SourceRequest).content === null || typeof (each as SourceRequest).content === 'string');
    const shaped = given as { rules?: unknown; sources?: unknown };
    if (
        typeof given !== 'object' ||
        given === null ||
        !Array.isArray(shaped.rules) ||
        !shaped.rules.every((rule) => typeof rule === 'string') ||
        !Array.isArray(shaped.sources) ||
        !shaped.sources.every(isSource)
    ) {
        throw refused();
    }
    return { rules: shaped.rules as string[], sources: shaped.sources };
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
            '--venv',
            JSON.stringify(args.environment.venv),
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
            process.stdout.write(JSON.stringify(ruleInfos()) + '\n');
            return;
        case 'parse':
            process.stdout.write(JSON.stringify(sources(fs.readFileSync(0, 'utf8')).map(parsedReport)) + '\n');
            return;
        case 'comments':
            process.stdout.write(JSON.stringify(sources(fs.readFileSync(0, 'utf8')).map(lupComments)) + '\n');
            return;
        case 'check': {
            const asked = checking(fs.readFileSync(0, 'utf8'));
            const engine = new Engine(args.root, args.environment);
            const reports = engine.check({
                op: 'check',
                build: build(),
                environment: args.environment,
                root: args.root,
                rules: asked.rules,
                sources: asked.sources,
            });
            process.stdout.write(JSON.stringify(reports) + '\n');
            return;
        }
        default:
            throw new Error(
                `no command named ${JSON.stringify(args.command)}: it's start, serve, check, comments, rules or parse`
            );
    }
}

// A rule the table doesn't hold is said without a stack, as the server says it; any
// other failure with its stack.
main().catch((error) => {
    const said =
        error instanceof UnknownRuleError || !(error instanceof Error)
            ? String(error instanceof Error ? error.message : error)
            : error.stack ?? error.message;
    process.stderr.write(said + '\n');
    process.exit(1);
});
