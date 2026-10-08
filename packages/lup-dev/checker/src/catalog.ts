// What an entry of lup's rule table (`lup_dev/catalog/rules.ts`) holds, and the
// table as the engine runs it.

import { rules } from 'catalog/rules';

import { File } from './file';
import { RuleInfo } from './protocol';

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

export class UnknownRuleError extends Error {}

export function ruleInfos(): RuleInfo[] {
    return Object.entries(table).map(([id, rule]) => ({
        id,
        mistake: rule.mistake,
        steer: rule.steer,
        examples: rule.examples,
    }));
}

// The rules a request selects, by id, refusing an id the table doesn't hold; none
// selects every rule.
export function selected(ids: string[] | null): [string, Rule][] {
    if (ids === null) {
        return Object.entries(table);
    }
    const unknown = ids.filter((id) => !(id in table));
    if (unknown.length > 0) {
        throw new UnknownRuleError(
            `no rule named ${unknown.map((id) => `\`${id}\``).join(', ')}; lup's rules are ` +
                Object.keys(table)
                    .map((id) => `\`${id}\``)
                    .join(', ')
        );
    }
    return ids.map((id) => [id, table[id]]);
}
