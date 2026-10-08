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

export interface Surface {
    exported: string[];
    classes: string[];
    signatures: Signature[];
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

// Every request names the build the client expects, so an engine left running from
// another build stops instead of answering with other rules.
interface RequestBase {
    build: string;
}

export interface CheckRequest extends RequestBase {
    op: 'check';
    root: string;
    // The rules the project selected, by id, of which one the engine doesn't have is
    // refused; none runs every rule the engine has.
    rules: string[] | null;
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
// - `stale`: the engine is from another build than the client expects, and stops;
// - `error`: the request was refused or failed, with why.
export interface Answer {
    build: string;
    stale: boolean;
    error: string | null;
    reports: FileReport[] | null;
    rules: RuleInfo[] | null;
    status: EngineStatus | null;
}
