// What travels between the engine and its Python client (`lup_dev/codescan/engine.py`),
// one JSON object per line.
//
// The reports mirror the models in `lup_dev/codescan/contract.py` and
// `lup_dev/codescan/directives.py` field for field: the client validates every answer
// into them, so a field renamed here fails there at once.

export interface Position {
    line: number;
    column: number;
}

export interface Span {
    start: Position;
    end: Position;
}

// A finding made whole: for lup's rules, what the check saw followed by the rule's
// mistake, and the rule's steer; for pyright's, its message, which may run over
// several lines, and no steer.
export interface Finding {
    path: string;
    span: Span;
    owner: 'lup' | 'pyright';
    rule: string;
    message: string;
    steer: string;
}

export type ParameterKind =
    | 'positional-only'
    | 'positional-or-keyword'
    | 'variadic'
    | 'keyword-only'
    | 'variadic-keyword';

export interface Parameter {
    name: string;
    kind: ParameterKind;
    annotation: string;
    has_default: boolean;
}

export interface Signature {
    name: string;
    parameters: Parameter[];
    returns: string;
}

// Where one name of the surface is written: an export by its entry in `__all__` or
// its binding, a class by its `class`, a function or method by its `def`, the line
// its name is on, counted from 1.
export interface Placed {
    kind: 'export' | 'class' | 'signature';
    name: string;
    line: number;
}

export interface Surface {
    exported: string[];
    classes: string[];
    signatures: Signature[];
    places: Placed[];
}

export interface Ignore {
    kind: 'ignore';
    line: number;
    covers: number;
    rule: string;
    why: string;
}

export interface Defer {
    kind: 'defer';
    line: number;
    why: string;
    issue: number | string | null;
    when: string | null;
}

export interface Note {
    kind: 'note';
    line: number;
    text: string;
}

export interface Malformed {
    kind: 'malformed';
    line: number;
    text: string;
    problem: string;
}

export type Directive = Ignore | Defer | Note | Malformed;

export interface FileReport {
    path: string;
    findings: Finding[];
    directives: Directive[];
    surface: Surface;
    imports: string[];
}

export interface RuleExamples {
    flags: { code: string; rewritten: string }[];
    passes: string[];
}

// A rule as the engine lists it, for the judge to check selections and `ignore`s
// against, and for `docs/rules.md`.
export interface RuleInfo {
    id: string;
    mistake: string;
    steer: string;
    examples: RuleExamples;
}

export interface EngineStatus {
    root: string;
    pid: number;
    idle_seconds: number;
    files: number;
    rss_bytes: number;
    peak_rss_bytes: number;
}

export interface SourceRequest {
    path: string;
    // The would-be content; null means the file as it stands on disk.
    content: string | null;
}

// How the engine finds the worktree's environment, from the project's runner
// (`EngineEnvironment` in `lup_dev/codescan/engine.py`): the command running the
// environment's Python, which names the interpreter, and the files, from the root,
// whose change means another environment.
export interface Environment {
    interpreter: string[];
    files: string[];
}

// Every request names the build the client expects, and the environment it was
// told of, so an engine left running from another build, or started with another
// runner, stops instead of answering with other rules or another environment.
interface RequestBase {
    build: string;
    environment: Environment;
}

// A rule selection as the declaration records it, mirroring `Selection` in
// `lup_dev/declaration/grammar.py` field for field: where it starts, then its
// operations in the order they were written. The reasons (`why`) and the anchors
// (`before`, `after`) travel too, and change nothing here: rules have no order.
export type Start =
    | { kind: 'below' }
    | { kind: 'default' }
    | { kind: 'all' }
    | { kind: 'only'; names: string[] }
    | { kind: 'of'; entries: string[] };

export type Operation =
    | { verb: 'add'; entries: string[] }
    | { verb: 'drop'; names: string[] }
    | { verb: 'replace'; name: string; entry: string }
    | { verb: 'edit'; entry: string };

export interface Selection {
    start: Start;
    operations: Operation[];
}

// One module's rules, mirroring `Selected` in `lup_dev/declaration/resolve.py`.
// - `default`: the module's own default for them, which `Rules.default()` names there;
// - `rules`: its selection with every layer applied over that default, so its
//   operations begin with the default's.
export interface Selected {
    module: string;
    rules: Selection;
    default: Selection;
}

export interface CheckRequest extends RequestBase {
    op: 'check';
    root: string;
    // Each module's rule selection, which the engine resolves against its table and
    // runs the union of; a name it doesn't hold, or one dropped that isn't there,
    // refuses the request.
    rules: Selected[];
    sources: SourceRequest[];
}

export interface ImportersRequest extends RequestBase {
    op: 'importers';
    root: string;
    changed: string[];
}

export interface RulesRequest extends RequestBase {
    op: 'rules';
}

export interface StatusRequest extends RequestBase {
    op: 'status';
}

export interface StopRequest extends RequestBase {
    op: 'stop';
}

export type Request = CheckRequest | ImportersRequest | RulesRequest | StatusRequest | StopRequest;

// One answer per request.
// - `stale`: the engine is from another build than the client expects, or was
//   started with another environment, and stops;
// - `error`: the request was refused or failed, with why.
export interface Answer {
    build: string;
    stale: boolean;
    error: string | null;
    reports: FileReport[] | null;
    rules: RuleInfo[] | null;
    status: EngineStatus | null;
}
