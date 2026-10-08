// The engine's socket: one long-lived process per worktree, reached by short-lived
// hook processes, answering one JSON line per request line.
//
// Requests run one at a time, checks first. An importers pass runs a step at a time
// between them, so an edit's check never waits for a whole pass. The engine stops
// when nothing has asked anything for its idle time, when told to, or when a client
// expects another build.

import * as fs from 'fs';
import * as net from 'net';
import * as readline from 'readline';

import { ruleInfos, UnknownRuleError } from './catalog';
import { Engine, ImportersJob } from './engine';
import { Answer, CheckRequest, ImportersRequest, Request } from './protocol';

export interface ServeOptions {
    root: string;
    socket: string;
    idleSeconds: number;
    build: string;
}

type Reply = (answer: Answer) => void;

interface Waiting<R extends Request> {
    request: R;
    reply: Reply;
}

interface Running {
    job: ImportersJob;
    reply: Reply;
}

export class Server {
    private readonly checks: Waiting<CheckRequest>[] = [];
    private readonly passes: Waiting<ImportersRequest>[] = [];
    private running: Running | undefined;
    private scheduled = false;
    private idle: NodeJS.Timeout | undefined;
    private readonly server: net.Server;

    constructor(private readonly engine: Engine, private readonly options: ServeOptions) {
        this.server = net.createServer((connection) => this.connected(connection));
    }

    listen(): Promise<void> {
        if (fs.existsSync(this.options.socket)) {
            fs.unlinkSync(this.options.socket);
        }
        return new Promise((ready, failed) => {
            this.server.once('error', failed);
            this.server.listen(this.options.socket, () => {
                fs.chmodSync(this.options.socket, 0o600);
                this.rest();
                ready();
            });
        });
    }

    private connected(connection: net.Socket) {
        const lines = readline.createInterface({ input: connection });
        lines.on('line', (line) => {
            if (!line.trim()) {
                return;
            }
            const reply = (answer: Answer) => {
                if (!connection.destroyed) {
                    connection.write(JSON.stringify(answer) + '\n');
                }
            };
            let request: Request;
            try {
                request = JSON.parse(line) as Request;
            } catch (error) {
                reply(this.answer({ error: `the request isn't JSON: ${String(error)}` }));
                return;
            }
            this.arrived({ request, reply });
        });
        connection.on('error', () => connection.destroy());
    }

    private arrived({ request, reply }: Waiting<Request>) {
        this.wake();
        // Stopping closes the socket before the answer goes out: a client reading the
        // answer then finds no engine to reconnect to, rather than one closing on it.
        if (request.build !== this.options.build) {
            this.stop();
            reply(this.answer({ stale: true }));
            return;
        }
        switch (request.op) {
            case 'stop':
                this.stop();
                reply(this.answer({}));
                return;
            case 'rules':
                reply(this.answer({ rules: ruleInfos() }));
                return;
            case 'status':
                reply(this.answer({ status: this.status() }));
                return;
            case 'importers':
                this.passes.push({ request, reply });
                break;
            case 'check':
                this.checks.push({ request, reply });
                break;
            default:
                reply(this.answer({ error: `no request named ${JSON.stringify((request as { op: unknown }).op)}` }));
                return;
        }
        this.schedule();
    }

    private schedule() {
        if (!this.scheduled) {
            this.scheduled = true;
            setImmediate(() => this.work());
        }
    }

    // One unit of work: a whole check, or one step of an importers pass.
    private work() {
        this.scheduled = false;
        const check = this.checks.shift();
        if (check) {
            check.reply(this.attempt(() => ({ reports: this.engine.check(check.request) })));
            this.schedule();
            return;
        }
        if (!this.running) {
            const pass = this.passes.shift();
            if (pass) {
                const started = this.attempt(() => {
                    this.running = {
                        job: this.engine.importers(pass.request.root, pass.request.changed),
                        reply: pass.reply,
                    };
                    return {};
                });
                if (started.error !== null) {
                    pass.reply(started);
                }
            }
        }
        if (this.running) {
            const running = this.running;
            let done = false;
            const stepped = this.attempt(() => {
                done = running.job.step();
                return {};
            });
            if (stepped.error !== null || done) {
                this.running = undefined;
                running.reply(stepped.error !== null ? stepped : this.answer({ reports: running.job.result() }));
            }
            this.schedule();
            return;
        }
        this.rest();
    }

    private attempt(work: () => Partial<Answer>): Answer {
        try {
            return this.answer(work());
        } catch (error) {
            const message =
                error instanceof UnknownRuleError || !(error instanceof Error)
                    ? String(error instanceof Error ? error.message : error)
                    : error.stack ?? error.message;
            return this.answer({ error: message });
        }
    }

    private answer(fields: Partial<Answer>): Answer {
        return { build: this.options.build, stale: false, error: null, reports: null, rules: null, status: null, ...fields };
    }

    private status() {
        return {
            root: this.engine.root,
            pid: process.pid,
            idle_seconds: this.options.idleSeconds,
            files: this.engine.program.trackedFiles().length,
            rss_bytes: process.memoryUsage().rss,
            peak_rss_bytes: process.resourceUsage().maxRSS * 1024,
        };
    }

    // Nothing to do: stop after the idle time unless asked something first.
    private rest() {
        this.wake();
        this.idle = setTimeout(() => {
            if (!this.running && this.checks.length === 0 && this.passes.length === 0) {
                this.stop();
            }
        }, this.options.idleSeconds * 1000);
    }

    private wake() {
        if (this.idle) {
            clearTimeout(this.idle);
            this.idle = undefined;
        }
    }

    // Stop taking requests. The process ends once its clients have read their last
    // answers, or shortly after if one never hangs up.
    private stop() {
        this.wake();
        this.server.close();
        if (fs.existsSync(this.options.socket)) {
            fs.unlinkSync(this.options.socket);
        }
        setTimeout(() => process.exit(0), 5000).unref();
    }
}
