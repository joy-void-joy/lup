// One warm pyright program for a worktree, loaded the way the pyright CLI loads it,
// kept in step with the disk without a file watcher, and analysed only when asked.
//
// Keeping in step, at the start of each request (`sync`):
// - a file checked with would-be content holds it until the next request, which
//   puts the disk's content back unless the edit landed, so a landed edit costs no
//   second check;
// - a file pyright read from disk is checked against the disk by its `stat`, and
//   pyright's own fingerprint decides whether it really changed;
// - a changed directory in the project's tree means files may have come or gone,
//   which re-enumerates the tracked files;
// - a changed directory on the import search path means packages were installed or
//   removed, which drops pyright's import cache;
// - a changed configuration (pyright's, or what decides uv's environment), or the
//   interpreter uv gave the worktree going or replaced, needs a new program, which
//   the engine builds, asking uv again.

import { spawnSync } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

import { InvalidatedReason } from 'pyright/analyzer/backgroundAnalysisProgram';
import { Program } from 'pyright/analyzer/program';
import { AnalyzerService } from 'pyright/analyzer/service';
import { IPythonMode } from 'pyright/analyzer/sourceFile';
import { SourceEnumerator } from 'pyright/analyzer/sourceEnumerator';
import { isUserCode } from 'pyright/analyzer/sourceFileInfoUtils';
import { CommandLineOptions } from 'pyright/common/commandLineOptions';
import { LogLevel, StderrConsole } from 'pyright/common/console';
import { Diagnostic } from 'pyright/common/diagnostic';
import { FullAccessHost } from 'pyright/common/fullAccessHost';
import { createFromRealFileSystem, RealTempFile } from 'pyright/common/realFileSystem';
import { createServiceProvider } from 'pyright/common/serviceProviderExtensions';
import { Uri } from 'pyright/common/uri/uri';
import { ParseFileResults } from 'pyright/parser/parser';
import { PyrightFileSystem } from 'pyright/pyrightFileSystem';

// What a program is set up from besides the project's files, so that a change to any
// of them needs a new program: pyright's configuration, what decides the environment
// uv gives the worktree (`pyproject.toml` again, `uv.toml`, `uv.lock`,
// `.python-version`), and that environment's interpreter, which decides where imports
// resolve, the project's own packages among them when they're installed editable.
const configurations = ['pyproject.toml', 'pyrightconfig.json', 'uv.toml', 'uv.lock', '.python-version'];

// Run in the worktree's environment, it names that environment's interpreter, as JSON.
const nameInterpreter = 'import json, sys; print(json.dumps(sys.executable))';

// The interpreter of the environment uv gives the worktree, as the gate's `uv run`
// finds it (`UV_PROJECT_ENVIRONMENT`, else `.venv`), made if it's missing and synced
// to `uv.lock`. `--frozen` reads the lock without relocking, so the judge never
// writes the worktree's `uv.lock`, and a project without one fails here. The session's
// `VIRTUAL_ENV` is left out: the judge inherits it from the hook that started it, it
// may be another worktree's, and uv warns about it.
function environmentOf(root: string): string {
    const inherited = { ...process.env };
    delete inherited.VIRTUAL_ENV;
    const asked = spawnSync('uv', ['run', '--frozen', '--quiet', 'python', '-c', nameInterpreter], {
        cwd: root,
        env: inherited,
        encoding: 'utf8',
    });
    if (asked.error) {
        throw new Error(`uv couldn't be run to find ${root}'s environment: ${asked.error.message}`);
    }
    if (asked.status !== 0) {
        const ended = asked.status === null ? `was killed by ${asked.signal}` : `exited with ${asked.status}`;
        throw new Error(`uv gave ${root} no environment: \`uv run\` ${ended}: ${asked.stderr.trim()}`);
    }
    const unnamed = () =>
        new Error(`${root}'s environment printed ${JSON.stringify(asked.stdout)}, not its interpreter's path as JSON`);
    let named: unknown;
    try {
        named = JSON.parse(asked.stdout);
    } catch {
        throw unnamed();
    }
    if (typeof named !== 'string') {
        throw unnamed();
    }
    return named;
}

interface Opened {
    uri: Uri;
    content: string;
    // Whether the content is would-be content rather than the disk's.
    overlay: boolean;
    stamp: string | undefined;
}

// What a file's `stat` says, to tell whether it changed: undefined once it's gone.
function stampOf(file: string): string | undefined {
    const stat = fs.statSync(file, { bigint: true, throwIfNoEntry: false });
    return stat ? `${stat.mtimeNs}:${stat.size}:${stat.ino}` : undefined;
}

function readIfThere(file: string): string | undefined {
    return fs.existsSync(file) ? fs.readFileSync(file, 'utf8') : undefined;
}

export class WarmProgram {
    readonly root: string;
    readonly service: AnalyzerService;
    readonly program: Program;
    private readonly setupStamps: Map<string, string | undefined>;
    private searchPathStamps = new Map<string, string | undefined>();
    private directoryStamps = new Map<string, string | undefined>();
    private readonly fileStamps = new Map<string, string | undefined>();
    private readonly opened = new Map<string, Opened>();
    private readonly parses = new Map<string, ParseFileResults>();
    private version = 0;

    constructor(root: string) {
        this.root = path.resolve(root);
        // The configuration is stamped before uv is asked, so a change while uv runs
        // builds another program at the next request.
        const configured = configurations.map((name) => path.join(this.root, name));
        const stamps = configured.map((file): [string, string | undefined] => [file, stampOf(file)]);
        const interpreter = environmentOf(this.root);
        this.setupStamps = new Map([...stamps, [interpreter, stampOf(interpreter)]]);
        const output = new StderrConsole(LogLevel.Error);
        const tempFile = new RealTempFile();
        const fileSystem = new PyrightFileSystem(createFromRealFileSystem(tempFile, output));
        const serviceProvider = createServiceProvider(fileSystem, output, tempFile);
        // As if `uv run pyright` ran from the worktree, as the gate runs it. The judge
        // runs from its own installed copy, so the worktree's environment is named
        // rather than found on the path, which the engine inherited from the hook that
        // started it and may lead to another worktree's environment.
        const commandLine = new CommandLineOptions(this.root, /* fromLanguageServer */ false);
        commandLine.configSettings.pythonPath = interpreter;
        // Which environment this program reads goes to the engine's log, since it decides
        // where the project's own imports resolve and nothing else shows it.
        process.stderr.write(`program for ${this.root} reads ${interpreter}, the environment uv gives it\n`);
        // Analysis runs when asked, never on pyright's own timers.
        commandLine.languageServerSettings.enableAmbientAnalysis = false;
        this.service = new AnalyzerService('lup-engine', serviceProvider, {
            console: output,
            hostFactory: () => new FullAccessHost(serviceProvider),
            shouldRunAnalysis: () => false,
        });
        this.service.setOptions(commandLine);
        if (!this.service.enumerateSourceFiles(/* maxSourceEnumeratorTime */ 0)) {
            throw new Error('pyright did not finish enumerating the source files');
        }
        this.program = this.service.backgroundAnalysisProgram.program;
        this.directoryStamps = this.stampDirectories();
        this.searchPathStamps = this.stampSearchPaths();
    }

    uri(file: string): Uri {
        return Uri.file(path.resolve(this.root, file), this.service.serviceProvider);
    }

    // Whether the configuration, or the interpreter uv gave the worktree, changed since
    // this program was set up: a new `uv.lock` to sync to, say, the environment
    // removed, or its Python replaced. An environment made again on the same Python is
    // the import search path changing, which `sync` sees.
    setupChanged(): boolean {
        return [...this.setupStamps].some(([file, stamp]) => stampOf(file) !== stamp);
    }

    trackedFiles(): Uri[] {
        return this.program
            .getSourceFileInfoList()
            .filter((info) => isUserCode(info))
            .map((info) => info.uri);
    }

    // Bring pyright's view in line with the disk, but for the files about to be given
    // would-be content.
    sync(keep: Set<string>) {
        let structural = false;
        for (const [key, entry] of this.opened) {
            if (keep.has(key)) {
                continue;
            }
            const stamp = stampOf(entry.uri.getFilePath());
            if (!entry.overlay && stamp === entry.stamp) {
                continue;
            }
            const content = readIfThere(entry.uri.getFilePath());
            if (content === undefined) {
                this.opened.delete(key);
                this.service.backgroundAnalysisProgram.setFileClosed(entry.uri);
                structural = true;
                continue;
            }
            this.setContents(entry.uri, content, /* overlay */ false, stamp);
        }

        const changed: Uri[] = [];
        for (const info of this.program.getSourceFileInfoList()) {
            if (!isUserCode(info) || info.isOpenByClient || info.sourceFile.isParseRequired()) {
                continue;
            }
            const stamp = stampOf(info.uri.getFilePath());
            const seen = this.fileStamps.has(info.uri.key);
            if (seen && this.fileStamps.get(info.uri.key) === stamp) {
                continue;
            }
            // Seen for the first time, pyright's fingerprint of what it read settles it.
            changed.push(info.uri);
            this.fileStamps.set(info.uri.key, stamp);
            structural ||= stamp === undefined;
        }
        if (changed.length > 0) {
            this.service.backgroundAnalysisProgram.markFilesDirty(changed, /* evenIfContentsAreSame */ false);
        }

        const directories = this.stampDirectories();
        if (!sameStamps(directories, this.directoryStamps)) {
            this.directoryStamps = directories;
            structural ||= this.retrack();
        }
        if (structural) {
            this.service.invalidateAndForceReanalysis(InvalidatedReason.SourceWatcherChanged);
            this.parses.clear();
        }

        const searchPaths = this.stampSearchPaths();
        if (!sameStamps(searchPaths, this.searchPathStamps)) {
            this.searchPathStamps = searchPaths;
            this.service.invalidateAndForceReanalysis(InvalidatedReason.LibraryWatcherChanged);
            this.parses.clear();
        }
    }

    // Give a file its content, as an editor holds an open buffer: would-be content
    // (`overlay`), or the disk's.
    setContents(uri: Uri, content: string, overlay: boolean, stamp?: string) {
        const known = this.opened.get(uri.key);
        if (known && known.content === content) {
            this.opened.set(uri.key, { ...known, overlay, stamp: stamp ?? known.stamp });
            return;
        }
        const before = known?.content ?? readIfThere(uri.getFilePath());
        this.version += 1;
        this.service.backgroundAnalysisProgram.setFileOpened(uri, this.version, content, {
            ipythonMode: IPythonMode.None,
            chainedFileUri: undefined,
        });
        if (before !== content) {
            // The file and everything importing it read the content anew.
            this.service.backgroundAnalysisProgram.markFilesDirty([uri], /* evenIfContentsAreSame */ true);
        }
        this.opened.set(uri.key, { uri, content, overlay, stamp: stamp ?? stampOf(uri.getFilePath()) });
    }

    // Open a file as it stands on disk, so its checks read what's there.
    openFromDisk(uri: Uri) {
        const content = readIfThere(uri.getFilePath());
        if (content === undefined) {
            throw new Error(`${uri.getFilePath()} doesn't exist`);
        }
        this.setContents(uri, content, /* overlay */ false, stampOf(uri.getFilePath()));
    }

    // pyright's check of one file: its errors and warnings.
    check(uri: Uri): Diagnostic[] {
        this.program.analyzeFile(uri);
        const sourceFile = this.program.getSourceFile(uri);
        if (!sourceFile) {
            throw new Error(`${uri.getFilePath()} is not part of the project pyright loaded`);
        }
        return sourceFile.getDiagnostics(this.program.configOptions) ?? [];
    }

    // A file's parse, held until it changes: pyright otherwise tokenizes the file
    // again each time its parse is asked for.
    parseResults(uri: Uri): ParseFileResults {
        const sourceFile = this.program.getSourceFile(uri);
        const output = sourceFile?.getParserOutput();
        const held = this.parses.get(uri.key);
        if (held && held.parserOutput === output) {
            return held;
        }
        const parse = sourceFile?.getParseResults();
        if (!parse) {
            throw new Error(`${uri.getFilePath()} has no parse: check it first`);
        }
        this.parses.set(uri.key, parse);
        return parse;
    }

    // Bind every tracked file, so each file's importers are known.
    bindNext(): boolean {
        const unbound = this.trackedFiles().find((uri) => this.program.getSourceFile(uri)?.isBindingRequired());
        if (!unbound) {
            return false;
        }
        this.program.getBoundSourceFile(unbound);
        return true;
    }

    // Enumerate the project's files again, and say whether the set changed.
    private retrack(): boolean {
        const options = this.program.configOptions;
        const enumerator = new SourceEnumerator(
            options.include,
            options.exclude,
            !!options.autoExcludeVenv,
            this.service.fs,
            this.service.serviceProvider.console()
        );
        const found = [...enumerator.enumerate(0).matches.values()];
        const before = new Set(
            this.program
                .getSourceFileInfoList()
                .filter((info) => info.isTracked)
                .map((info) => info.uri.key)
        );
        const changed = found.length !== before.size || found.some((uri) => !before.has(uri.key));
        if (changed) {
            this.service.backgroundAnalysisProgram.setTrackedFiles(found);
        }
        return changed;
    }

    // The directories holding the project's files, up to the worktree's root.
    private stampDirectories(): Map<string, string | undefined> {
        const directories = new Set<string>([this.root]);
        for (const uri of this.trackedFiles()) {
            for (let directory = path.dirname(uri.getFilePath()); directory.startsWith(this.root); ) {
                directories.add(directory);
                const parent = path.dirname(directory);
                if (parent === directory) {
                    break;
                }
                directory = parent;
            }
        }
        return new Map([...directories].map((directory) => [directory, stampOf(directory)]));
    }

    private stampSearchPaths(): Map<string, string | undefined> {
        const paths = this.program.importResolver.getPythonSearchPaths().map((uri) => uri.getFilePath());
        return new Map(paths.map((searchPath) => [searchPath, stampOf(searchPath)]));
    }
}

function sameStamps(left: Map<string, string | undefined>, right: Map<string, string | undefined>): boolean {
    return left.size === right.size && [...left].every(([key, stamp]) => right.has(key) && right.get(key) === stamp);
}
