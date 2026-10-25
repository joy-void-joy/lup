// One warm pyright program for a worktree, loaded the way the pyright CLI loads it,
// kept in step with the disk without a file watcher, and analysed only when asked.
//
// The host never runs a project's environment: the program reads it as files, the
// directory the project's runner names (`Runner.venv`), and starts no process
// (`NoAccessHost`), whatever pyright's configuration says. Everything it reads is
// confined to the worktree, that environment and its own standard-library stubs
// (`confined.ts`).
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
//   removed, which drops pyright's import cache and reads the search path again;
// - a changed configuration (pyright's, or the files the project's runner says decide
//   its environment), or the environment's `pyvenv.cfg` made, removed or replaced,
//   needs a new program, which the engine builds.

import * as fs from 'fs';
import * as path from 'path';

import { InvalidatedReason } from 'pyright/analyzer/backgroundAnalysisProgram';
import { ImportLogger } from 'pyright/analyzer/importLogger';
import { ImportResolver } from 'pyright/analyzer/importResolver';
import { Program } from 'pyright/analyzer/program';
import { findPythonSearchPaths, getTypeShedFallbackPath } from 'pyright/analyzer/pythonPathUtils';
import { AnalyzerService } from 'pyright/analyzer/service';
import { IPythonMode } from 'pyright/analyzer/sourceFile';
import { SourceEnumerator } from 'pyright/analyzer/sourceEnumerator';
import { isUserCode } from 'pyright/analyzer/sourceFileInfoUtils';
import { CommandLineOptions } from 'pyright/common/commandLineOptions';
import { ConfigOptions } from 'pyright/common/configOptions';
import { LogLevel, StderrConsole } from 'pyright/common/console';
import { Diagnostic } from 'pyright/common/diagnostic';
import { Host, NoAccessHost } from 'pyright/common/host';
import { PythonVersion } from 'pyright/common/pythonVersion';
import { createFromRealFileSystem, RealTempFile } from 'pyright/common/realFileSystem';
import { ServiceProvider } from 'pyright/common/serviceProvider';
import { createServiceProvider } from 'pyright/common/serviceProviderExtensions';
import { Uri } from 'pyright/common/uri/uri';
import { ParseFileResults } from 'pyright/parser/parser';
import { PyrightFileSystem } from 'pyright/pyrightFileSystem';

import { ConfinedFileSystem, named, Places, resolved } from './confined';
import { Environment } from './protocol';

// pyright's own configuration. A program is set up from these, from the files the
// project's runner says decide its environment (for uv, `pyproject.toml` again,
// `uv.toml`, `uv.lock`, `.python-version`), and from that environment's
// `pyvenv.cfg`, which says its Python; a change to any of them needs a new program.
const pyrightConfigurations = ['pyproject.toml', 'pyrightconfig.json'];

// The Python a virtual environment's `pyvenv.cfg` records, read as data: its
// `version_info` (`3.14`, `3.14.0`), as uv and virtualenv write it, else its
// `version`, as `python -m venv` does; undefined where it records neither.
function recordedVersion(places: Places, configuration: string): PythonVersion | undefined {
    const lines = places.read(configuration)?.toString('utf8').split(/\r?\n/) ?? [];
    const pairs = lines.map((line): [string, string] => {
        const [key, ...value] = line.split('=');
        return [key.trim(), value.join('=').trim()];
    });
    const recorded = new Map(pairs);
    const version = recorded.get('version_info') ?? recorded.get('version');
    return version === undefined ? undefined : PythonVersion.fromString(version);
}

// The platform the engine runs on, the host's, which its environments are made for,
// as pyright names it.
function hostPlatform(): 'Linux' | 'Darwin' | 'Windows' | undefined {
    switch (process.platform) {
        case 'linux':
            return 'Linux';
        case 'darwin':
            return 'Darwin';
        case 'win32':
            return 'Windows';
        default:
            return undefined;
    }
}

// pyright's import resolver, reading the environment the runner names, whatever
// pyright's configuration names (its `venvPath` and `venv`): its `site-packages`, and
// the paths its `.pth` files list, as pyright reads a virtual environment's own. An
// `import` line of a `.pth` file is code, which pyright skips; no interpreter runs.
class EnvironmentResolver extends ImportResolver {
    private searchPaths: Uri[] | undefined;

    constructor(
        serviceProvider: ServiceProvider,
        private configured: ConfigOptions,
        host: Host,
        private readonly venv: string | undefined
    ) {
        super(serviceProvider, configured, host);
    }

    override setConfigOptions(configOptions: ConfigOptions): void {
        this.configured = configOptions;
        super.setConfigOptions(configOptions);
    }

    // Packages installed or removed may change the search path itself: an editable
    // install adds a `.pth` file.
    override invalidateCache(): void {
        this.searchPaths = undefined;
        super.invalidateCache();
    }

    override getPythonSearchPaths(importLogger?: ImportLogger): Uri[] {
        if (this.searchPaths === undefined) {
            this.searchPaths = this.venv === undefined ? [] : this.found(this.venv, importLogger);
        }
        return this.searchPaths;
    }

    private found(venv: string, importLogger?: ImportLogger): Uri[] {
        const named = new ConfigOptions(this.configured.projectRoot);
        named.venvPath = Uri.file(path.dirname(venv), this.serviceProvider);
        named.venv = path.basename(venv);
        named.defaultPythonVersion = this.configured.defaultPythonVersion;
        const found = findPythonSearchPaths(this.fileSystem, named, this.host, importLogger) ?? [];
        const cased = found.map((each) => this.fileSystem.realCasePath(each));
        return [...new Map(cased.map((each) => [each.key, each])).values()];
    }
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

export class WarmProgram {
    readonly root: string;
    readonly service: AnalyzerService;
    readonly program: Program;
    private readonly places: Places;
    private readonly setupStamps: Map<string, string | undefined>;
    private searchPathStamps = new Map<string, string | undefined>();
    private directoryStamps = new Map<string, string | undefined>();
    private readonly fileStamps = new Map<string, string | undefined>();
    private readonly opened = new Map<string, Opened>();
    private readonly parses = new Map<string, ParseFileResults>();
    private version = 0;

    constructor(root: string, environment: Environment) {
        this.root = path.resolve(root);
        const venv = environment.venv === null ? undefined : path.resolve(this.root, environment.venv);
        const recorded = venv === undefined ? undefined : path.join(venv, 'pyvenv.cfg');
        // The configuration is stamped before it's read, so a change while the program
        // is set up builds another at the next request.
        const configured = [...new Set([...pyrightConfigurations, ...environment.files])].map((name) =>
            path.join(this.root, name)
        );
        const stamped = recorded === undefined ? configured : [...configured, recorded];
        this.setupStamps = new Map(stamped.map((file): [string, string | undefined] => [file, stampOf(file)]));
        const output = new StderrConsole(LogLevel.Error);
        const tempFile = new RealTempFile();
        const real = createFromRealFileSystem(tempFile, output);
        const typeshed = getTypeShedFallbackPath(real)?.getFilePath();
        this.places = new Places([
            resolved(this.root) ?? this.root,
            ...(venv === undefined ? [] : [named(venv)]),
            ...(typeshed === undefined ? [] : [resolved(typeshed) ?? typeshed]),
        ]);
        const fileSystem = new PyrightFileSystem(new ConfinedFileSystem(real, this.places));
        const serviceProvider = createServiceProvider(fileSystem, output, tempFile);
        // As if the gate's pyright step ran from the worktree, its Python the one the
        // environment records, unless pyright's configuration names one, and its
        // platform the host's.
        const commandLine = new CommandLineOptions(this.root, /* fromLanguageServer */ false);
        const version = recorded === undefined ? undefined : recordedVersion(this.places, recorded);
        commandLine.configSettings.pythonVersion = version;
        commandLine.configSettings.pythonPlatform = hostPlatform();
        // Which environment this program reads goes to the engine's log, since it decides
        // where the project's own imports resolve and nothing else shows it.
        const python = version === undefined ? 'no Python its `pyvenv.cfg` records' : PythonVersion.toString(version);
        const read = venv === undefined ? 'no environment' : `the environment at ${venv}, on ${python}`;
        process.stderr.write(`program for ${this.root} reads ${read}, as the runner names it\n`);
        // Analysis runs when asked, never on pyright's own timers.
        commandLine.languageServerSettings.enableAmbientAnalysis = false;
        this.service = new AnalyzerService('lup-engine', serviceProvider, {
            console: output,
            hostFactory: () => new NoAccessHost(),
            importResolverFactory: (provider, options, host) => new EnvironmentResolver(provider, options, host, venv),
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

    // Whether the configuration, or the environment's `pyvenv.cfg`, changed since this
    // program was set up: the environment made, removed, or made again.
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
            const content = this.readIfThere(entry.uri.getFilePath());
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
        const before = known?.content ?? this.readIfThere(uri.getFilePath());
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
        const content = this.readIfThere(uri.getFilePath());
        if (content === undefined) {
            throw new Error(
                `${uri.getFilePath()} doesn't exist, or resolves outside the worktree and its environment`
            );
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

    // A file's content, where it's there and inside the places the program reads.
    private readIfThere(file: string): string | undefined {
        return this.places.read(file)?.toString('utf8');
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
