// What an entry of lup's rule table (`lup_dev/catalog/rules.ts`) holds, the table as
// the engine runs it, and the rules a request's selections choose from it.

import { rules } from 'catalog/rules';

import { File } from './file';
import { Operation, RuleInfo, Selected, Selection, Start } from './protocol';

export interface Rule {
    // The mistake the rule prevents, as a sentence that stands alone.
    mistake: string;
    // Where it steers instead, as a sentence that stands alone.
    steer: string;
    // How it recognises its case: reports where it found it, and what it saw there.
    check(file: File): void;
    // The rule's specification, which the engine's tests run.
    examples: {
        // Code the rule flags, each with the same code done the steer's way, which
        // passes every rule, ruff and pyright.
        flags: { code: string; rewritten: string }[];
        // Near misses the rule must not flag.
        passes: string[];
    };
}

export type Catalog = Record<string, Rule>;

const table: Catalog = rules;

// A selection the table can't resolve, said as the declaration's own errors say it
// (`lup_dev/declaration/grammar.py`): a name the table doesn't hold, one dropped or
// replaced that isn't there, one added that its own layer already gave.
export class SelectionError extends Error {}

// A rule a selection holds so far, with the layer of its chain that last gave it: the
// operation's (`Operation.layer`), 0 for one its start names itself, and none for one
// the defaults gave to `Rules.default()` or `Rules.all()`, below every layer, as
// `Placed.layer` says in Python.
interface Given {
    id: string;
    layer: number | null;
}

// The rules as the engine lists them: every rule of the table, or, given each
// module's selection, those their union runs, as a check resolves them.
export function ruleInfos(selections?: Selected[]): RuleInfo[] {
    const listed = selections === undefined ? Object.entries(table) : selected(selections);
    return listed.map(([id, rule]) => ({
        id,
        mistake: rule.mistake,
        steer: rule.steer,
        examples: rule.examples,
    }));
}

// The rules a request's selections choose: each module's resolved against the table,
// then their union, in the table's order.
export function selected(selections: Selected[]): [string, Rule][] {
    const chosen = new Set(selections.flatMap((one) => resolved(one)));
    return Object.entries(table).filter(([id]) => chosen.has(id));
}

// One module's rules (`docs/declaration.md`, *Selecting the rules*). Its own default is
// resolved from nothing beneath it. Its selection is every layer applied over that
// default, so its operations begin with the default's: `Rules()` starts from nothing
// beneath them, and a layer's `Rules.default()` from the default resolved.
function resolved(one: Selected): string[] {
    const where = `\`${one.module}\`'s rules`;
    if (one.default.start.kind === 'default') {
        throw new SelectionError(
            `${where} have \`Rules.default()\` as their own default, which is that default itself: ` +
                'start it from `Rules.all()`, `Rules.only(…)` or `Rules()`'
        );
    }
    const own = applied(where, one.default, []);
    return applied(where, one.rules, own);
}

// A selection's rules: where it starts, then each operation in the order written,
// `defaults` being what `Rules.default()` starts from.
function applied(where: string, selection: Selection, defaults: string[]): string[] {
    const kind = selection.start.kind;
    const layer = kind === 'default' || kind === 'all' ? null : 0;
    const start = started(where, selection.start, defaults).map((id) => ({ id, layer }));
    return selection.operations
        .reduce((given, operation) => operated(where, operation, given), start)
        .map((each) => each.id);
}

function started(where: string, start: Start, defaults: string[]): string[] {
    switch (start.kind) {
        case 'below':
            return [];
        case 'default':
            return defaults;
        case 'all':
            return Object.keys(table);
        case 'only':
            return picked(where, 'Rules.only', start.names);
        case 'of':
            return picked(where, 'Rules.of', start.entries);
        default:
            throw new SelectionError(
                `${where} start from ${JSON.stringify(start)}: a selection starts from ` +
                    '`below`, `default`, `all`, `only` or `of`'
            );
    }
}

// The rules `given` holds with `operation` applied. An add of a rule from below, a
// layer below's or the defaults', keeps it, now given by the add's layer, as
// `Selection.taken` puts an entry on one there in Python; one its own layer gave is
// refused.
function operated(where: string, operation: Operation, given: Given[]): Given[] {
    const ids = given.map((each) => each.id);
    const layer = operation.layer;
    switch (operation.verb) {
        case 'add': {
            held(where, 'Rules.add', operation.entries);
            const mine = given.filter((each) => each.layer === layer).map((each) => each.id);
            const twice = operation.entries.filter(
                (id, at) => mine.includes(id) || operation.entries.indexOf(id) < at
            );
            if (twice.length > 0) {
                throw new SelectionError(
                    `${where}: \`Rules.add\` names ${listed(twice)}, already there: ` +
                        '`.replace` puts another in its place'
                );
            }
            const kept = given.map((each) =>
                operation.entries.includes(each.id) ? { id: each.id, layer } : each
            );
            const added = operation.entries.filter((id) => !ids.includes(id));
            return [...kept, ...added.map((id) => ({ id, layer }))];
        }
        case 'drop':
            there(where, 'Rules.drop', operation.names, ids);
            return given.filter((each) => !operation.names.includes(each.id));
        case 'replace': {
            there(where, 'Rules.replace', [operation.name], ids);
            held(where, 'Rules.replace', [operation.entry]);
            if (operation.entry !== operation.name && ids.includes(operation.entry)) {
                throw new SelectionError(
                    `${where}: \`Rules.replace\` puts \`${operation.entry}\` in place of ` +
                        `\`${operation.name}\`, but \`${operation.entry}\` is already there`
                );
            }
            return given.map((each) =>
                each.id === operation.name ? { id: operation.entry, layer } : each
            );
        }
        case 'edit':
            throw new SelectionError(
                `${where}: \`.edit\` puts a layer on a module, and a rule has none to take; ` +
                    '`.replace` puts another rule in its place'
            );
        default:
            throw new SelectionError(
                `${where}: no operation named ${JSON.stringify((operation as { verb: unknown }).verb)}; ` +
                    "a rule selection's are `add`, `drop` and `replace`"
            );
    }
}

// The rules a selection starts from by name, each once, each one the table holds.
function picked(where: string, verb: string, names: string[]): string[] {
    held(where, verb, names);
    const twice = names.filter((name, at) => names.indexOf(name) < at);
    if (twice.length > 0) {
        throw new SelectionError(`${where}: \`${verb}\` starts from ${listed(twice)} more than once`);
    }
    return names;
}

// Refuse a name the table doesn't hold, naming the ones it does.
function held(where: string, verb: string, names: string[]) {
    const unknown = names.filter((name) => !(name in table));
    if (unknown.length > 0) {
        throw new SelectionError(
            `${where}: \`${verb}\` names ${listed(unknown)}, which isn't one of lup's rules; ` +
                `they are ${listed(Object.keys(table))}`
        );
    }
}

// Refuse a name that isn't among those selected so far, naming the ones that are.
function there(where: string, verb: string, names: string[], ids: string[]) {
    const missing = names.filter((name) => !ids.includes(name));
    if (missing.length > 0) {
        throw new SelectionError(
            `${where}: \`${verb}\` names ${listed(missing)}, which isn't there; there are ${listed(ids)}`
        );
    }
}

// Name each of `names` in backticks, for a message, as `listed` does in Python.
function listed(names: string[]): string {
    const quoted = names.map((name) => `\`${name}\``);
    const last = quoted.pop();
    if (last === undefined) {
        return 'none';
    }
    return quoted.length > 0 ? `${quoted.join(', ')} and ${last}` : last;
}
