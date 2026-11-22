// What an entry of lup's rule table (`rules/`) holds, the table as the engine runs it,
// and the rules a request names from it.

import { File } from './file';
import { Category, Reads, RuleInfo } from './protocol';
import { rules } from './rules';

export interface Rule {
    // The mistake the rule prevents, as a sentence that stands alone.
    mistake: string;
    // Where it steers instead, as a sentence that stands alone.
    steer: string;
    // When it's told, and whether the gate fails on it: `design`, told right after a
    // write and failing the gate; `spelling`, about how a correct thing is written,
    // listed at the gate alone and failing it; `heuristic`, a guess over prose, listed
    // at the gate alone and never failing it.
    category: Category;
    // Which files it reads: `code`, every file but a test's (the default), or
    // `tests`, a test's and a module's promises, whose checks are what it's about.
    reads?: Reads;
    // How it recognises its case: reports where it found it, and what it saw there.
    check(file: File): void;
    // The rule's specification, which the module's promises check.
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

// A request naming a rule the table doesn't hold.
export class UnknownRuleError extends Error {}

// Every rule of the table, as the engine lists it, in the table's order.
export function ruleInfos(): RuleInfo[] {
    return Object.entries(table).map(([id, rule]) => ({
        id,
        mistake: rule.mistake,
        steer: rule.steer,
        category: rule.category,
        reads: rule.reads ?? 'code',
        examples: rule.examples,
    }));
}

// The rules a request names, in the table's order. The declaration resolves which
// rules a project runs (`CodeRules.rules`), so a name the table doesn't hold is a
// client from another build, refused naming those it holds.
export function selected(ids: string[]): [string, Rule][] {
    const unknown = ids.filter((id) => !(id in table));
    if (unknown.length > 0) {
        throw new UnknownRuleError(
            `no rule named ${unknown.map((id) => `\`${id}\``).join(', ')}: the table holds ` +
                Object.keys(table)
                    .map((id) => `\`${id}\``)
                    .join(', ')
        );
    }
    const chosen = new Set(ids);
    return Object.entries(table).filter(([id]) => chosen.has(id));
}
