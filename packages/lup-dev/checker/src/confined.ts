// What the engine reads of the disk: the worktree, its environment, and its own
// standard-library stubs, and nothing else, whatever pyright's configuration says or
// a link points at.
//
// The host never runs a project's environment: the engine reads it as files. A room
// writes the worktree and its environment, which git ignores and nothing judges, so
// a link there, or a `.pth` line, could lead pyright to a file elsewhere on the host,
// which it would read as a module and could quote in a finding. So every path is
// resolved, its links followed, and refused unless it resolves inside one of the
// places, a path that isn't there by its nearest parent that is: refused, a path
// isn't there. A file's content is checked on the file opened, through
// `/proc/self/fd`, so a link swapped between the check and the read can't win; where
// there's no `/proc`, the path is resolved first. A file is opened without blocking,
// and read only where it's a regular file, so a named pipe can't hold the engine.

import * as fs from 'fs';
import * as path from 'path';

import { FileSystem, MkDirOptions, Stats } from 'pyright/common/fileSystem';
import { FileWatcher, FileWatcherEventHandler } from 'pyright/common/fileWatcher';
import { Uri } from 'pyright/common/uri/uri';

// Where an opened file descriptor's file is, as the kernel names it.
const opened = '/proc/self/fd';

// The places the engine reads, each given resolved (`resolved`, `named`).
export class Places {
    private readonly descriptors = fs.existsSync(opened);

    constructor(readonly roots: string[]) {}

    // Whether a path, resolved, is inside one of the places.
    holds(real: string): boolean {
        return this.roots.some((root) => real === root || real.startsWith(root + path.sep));
    }

    // Whether `file` resolves inside one of the places.
    reaches(file: string): boolean {
        const real = resolved(file);
        return real !== undefined && this.holds(real);
    }

    // The content of `file`, where it's a regular file resolving inside one of the
    // places; undefined where it isn't there, or is refused.
    read(file: string): Buffer | undefined {
        const before = this.descriptors ? undefined : resolved(file);
        if (!this.descriptors && (before === undefined || !this.holds(before))) {
            return undefined;
        }
        let descriptor: number;
        try {
            descriptor = fs.openSync(file, fs.constants.O_RDONLY | fs.constants.O_NONBLOCK);
        } catch {
            return undefined;
        }
        try {
            if (this.descriptors && !this.holds(fs.readlinkSync(`${opened}/${descriptor}`))) {
                return undefined;
            }
            if (!fs.fstatSync(descriptor).isFile()) {
                return undefined;
            }
            return fs.readFileSync(descriptor);
        } catch {
            return undefined;
        } finally {
            fs.closeSync(descriptor);
        }
    }
}

// Where `file` resolves, its links followed; a path that isn't there resolves as its
// nearest parent that is, with the rest of the path after it, so a missing file
// under a link out of a place resolves out with it. Undefined where nothing of it
// resolves.
export function resolved(file: string): string | undefined {
    let at = path.resolve(file);
    let rest = '';
    for (;;) {
        try {
            return path.join(fs.realpathSync.native(at), rest);
        } catch {
            const parent = path.dirname(at);
            if (parent === at) {
                return undefined;
            }
            rest = path.join(path.basename(at), rest);
            at = parent;
        }
    }
}

// A place by its name: its parent's links followed, its own name as given, so a
// place that is itself a link, as a room may make the environment, holds nothing
// beyond it.
export function named(place: string): string {
    const absolute = path.resolve(place);
    const parent = path.dirname(absolute);
    return parent === absolute ? absolute : path.join(resolved(parent) ?? parent, path.basename(absolute));
}

function refused(operation: string, uri: Uri): Error {
    const file = uri.getFilePath();
    return Object.assign(new Error(`ENOENT: no such file or directory, ${operation} '${file}'`), {
        code: 'ENOENT',
        path: file,
    });
}

function unwritten(): Error {
    return new Error('the engine writes nothing');
}

// pyright's real file system, confined to `places`: a path resolving outside them
// isn't there, and nothing is written.
export class ConfinedFileSystem implements FileSystem {
    constructor(private readonly real: FileSystem, private readonly places: Places) {}

    private reaches(uri: Uri): boolean {
        return this.places.reaches(uri.getFilePath());
    }

    private reached(operation: string, uri: Uri) {
        if (!this.reaches(uri)) {
            throw refused(operation, uri);
        }
    }

    private content(uri: Uri): Buffer {
        // A file inside a zip or an egg isn't a file the kernel opens: its archive is
        // checked by its path, as a directory is.
        if (this.real.isInZip(uri)) {
            this.reached('open', uri);
            return this.real.readFileSync(uri);
        }
        const content = this.places.read(uri.getFilePath());
        if (content === undefined) {
            throw refused('open', uri);
        }
        return content;
    }

    existsSync(uri: Uri): boolean {
        return this.reaches(uri) && this.real.existsSync(uri);
    }

    chdir(_uri: Uri): void {
        throw new Error('the engine stays where it started');
    }

    readdirEntriesSync(uri: Uri): fs.Dirent[] {
        this.reached('scandir', uri);
        return this.real.readdirEntriesSync(uri);
    }

    readdirSync(uri: Uri): string[] {
        this.reached('scandir', uri);
        return this.real.readdirSync(uri);
    }

    readFileSync(uri: Uri, encoding?: null): Buffer;
    readFileSync(uri: Uri, encoding: BufferEncoding): string;
    readFileSync(uri: Uri, encoding?: BufferEncoding | null): string | Buffer;
    readFileSync(uri: Uri, encoding?: BufferEncoding | null): string | Buffer {
        const content = this.content(uri);
        return encoding ? content.toString(encoding) : content;
    }

    statSync(uri: Uri): Stats {
        this.reached('stat', uri);
        return this.real.statSync(uri);
    }

    realpathSync(uri: Uri): Uri {
        return this.reaches(uri) ? this.real.realpathSync(uri) : uri;
    }

    getModulePath(): Uri {
        return this.real.getModulePath();
    }

    readFile(uri: Uri): Promise<Buffer> {
        return new Promise((resolve) => resolve(this.content(uri)));
    }

    readFileText(uri: Uri, encoding: BufferEncoding = 'utf8'): Promise<string> {
        return new Promise((resolve) => resolve(this.content(uri).toString(encoding)));
    }

    realCasePath(uri: Uri): Uri {
        return this.reaches(uri) ? this.real.realCasePath(uri) : uri;
    }

    isMappedUri(uri: Uri): boolean {
        return this.real.isMappedUri(uri);
    }

    getOriginalUri(mappedUri: Uri): Uri {
        return this.real.getOriginalUri(mappedUri);
    }

    getMappedUri(originalUri: Uri): Uri {
        return this.real.getMappedUri(originalUri);
    }

    isInZip(uri: Uri): boolean {
        return this.reaches(uri) && this.real.isInZip(uri);
    }

    mkdirSync(_uri: Uri, _options?: MkDirOptions): void {
        throw unwritten();
    }

    writeFileSync(_uri: Uri, _data: string | Buffer, _encoding: BufferEncoding | null): void {
        throw unwritten();
    }

    unlinkSync(_uri: Uri): void {
        throw unwritten();
    }

    rmdirSync(_uri: Uri): void {
        throw unwritten();
    }

    createFileSystemWatcher(uris: Uri[], listener: FileWatcherEventHandler): FileWatcher {
        return this.real.createFileSystemWatcher(uris, listener);
    }

    createReadStream(uri: Uri): fs.ReadStream {
        this.reached('open', uri);
        return this.real.createReadStream(uri);
    }

    createWriteStream(_uri: Uri): fs.WriteStream {
        throw unwritten();
    }

    copyFileSync(_uri: Uri, _dst: Uri): void {
        throw unwritten();
    }

    mapDirectory(
        mappedUri: Uri,
        originalUri: Uri,
        filter?: (originalUri: Uri, fs: FileSystem) => boolean
    ): ReturnType<FileSystem['mapDirectory']> {
        return this.real.mapDirectory(mappedUri, originalUri, filter);
    }
}
