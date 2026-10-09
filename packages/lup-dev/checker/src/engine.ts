// The engine for one worktree: checking files with lup's selected rules, and
// re-checking the files that import changed ones for their type errors.

import * as fs from 'fs';
import * as path from 'path';

import { collectImportedByRecursively } from 'pyright/analyzer/sourceFileInfoUtils';
import { SourceFileInfo } from 'pyright/analyzer/sourceFileInfo';
import { isUserCode } from 'pyright/analyzer/sourceFileInfoUtils';
import { Uri } from 'pyright/common/uri/uri';

import { selected } from './catalog';
import { WarmProgram } from './program';
import { CheckRequest, FileReport } from './protocol';
import { fullReport, typeReport } from './report';

export class Engine {
    private warm: WarmProgram;
    // Bumped by every check, so a long importers pass knows to look at the disk
    // again before going on.
    generation = 0;

    constructor(readonly root: string) {
        this.warm = new WarmProgram(root);
    }

    get program(): WarmProgram {
        return this.warm;
    }

    // Bring the program in line with the disk, with a new one if the configuration or
    // the interpreter uv gave the worktree changed, but for the files about to be given
    // would-be content. A new program that fails (uv gives no environment) leaves the
    // old stamps in place, so each request tries again, failing with uv's message.
    fresh(keep: Set<string> = new Set()) {
        if (this.warm.setupChanged()) {
            this.warm.service.dispose();
            this.warm = new WarmProgram(this.root);
        }
        this.warm.sync(keep);
    }

    check(request: CheckRequest): FileReport[] {
        this.ownsRoot(request.root);
        const rules = selected(request.rules);
        this.generation += 1;
        const sources = request.sources.map((source) => ({ source, uri: this.warm.uri(source.path) }));
        this.fresh(new Set(sources.filter(({ source }) => source.content !== null).map(({ uri }) => uri.key)));
        for (const { source, uri } of sources) {
            if (source.content === null) {
                this.warm.openFromDisk(uri);
            } else {
                this.warm.setContents(uri, source.content, /* overlay */ true);
            }
        }
        return sources.map(({ source, uri }) => fullReport(this.warm, uri, source.path, rules));
    }

    importers(root: string, changed: string[]): ImportersJob {
        this.ownsRoot(root);
        return new ImportersJob(this, changed);
    }

    // The path a report names a project file by: relative to the worktree's root.
    relative(uri: Uri): string {
        return path.relative(this.root, uri.getFilePath()).split(path.sep).join('/');
    }

    private ownsRoot(root: string) {
        if (fs.realpathSync(path.resolve(root)) !== fs.realpathSync(this.root)) {
            throw new Error(`this engine checks ${this.root}, not ${root}`);
        }
    }
}

// The files importing changed ones, re-checked for type errors one step at a time,
// so a check waiting behind the pass runs between two steps. A check that comes
// between them may change what's on disk: the pass then looks again, and checks once
// more whatever that made stale.
export class ImportersJob {
    private seen = -1;
    private targets: Uri[] | undefined;
    private readonly reports = new Map<string, FileReport>();

    constructor(private readonly engine: Engine, private readonly changed: string[]) {}

    // Take one step; say whether the pass is done.
    step(): boolean {
        if (this.seen !== this.engine.generation) {
            this.engine.fresh();
            this.seen = this.engine.generation;
            this.targets = undefined;
        }
        const warm = this.engine.program;
        if (warm.bindNext()) {
            return false;
        }
        this.targets ??= this.importing();
        const next = this.targets.find(
            (uri) => !this.reports.has(uri.key) || warm.program.getSourceFile(uri)?.isCheckingRequired()
        );
        if (!next) {
            return true;
        }
        this.reports.set(next.key, typeReport(warm, next, this.engine.relative(next)));
        return false;
    }

    result(): FileReport[] {
        return (this.targets ?? []).flatMap((uri) => this.reports.get(uri.key) ?? []);
    }

    // The project's files importing a changed one, directly or through others. A
    // changed file that's gone leaves its importers unknown, so every file is.
    private importing(): Uri[] {
        const warm = this.engine.program;
        const changed = this.changed.map((file) => warm.uri(file));
        const everything = warm.trackedFiles();
        const gone = changed.some((uri) => !fs.existsSync(uri.getFilePath()));
        const found = new Set<SourceFileInfo>();
        if (!gone) {
            for (const uri of changed) {
                const info = warm.program.getSourceFileInfo(uri);
                if (info) {
                    collectImportedByRecursively(info, found);
                }
            }
        }
        const keys = new Set(changed.map((uri) => uri.key));
        const candidates = gone ? everything : [...found].filter((info) => isUserCode(info)).map((info) => info.uri);
        return candidates.filter((uri) => !keys.has(uri.key)).sort((a, b) => (a.key < b.key ? -1 : 1));
    }
}
