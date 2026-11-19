// lup's code rules: one entry per rule, keyed by its name, each holding the mistake it
// prevents, where it steers, its category, its check, and its examples, grouped by
// what they're about, one file each.
//
// A check reads pyright's tree and asks pyright's type evaluator, through the
// engine's helpers (`file.ts`), and reports where it found its case and what it saw
// there; the engine adds the mistake and the steer. Each check stays short: what
// checks share is a helper, outside the table.
//
// The examples are the rule's specification, which the module's promises check:
// - each of `flags` gets a finding from this rule and no other, and its `rewritten`,
//   the same code done the steer's way, passes every rule, ruff and pyright;
// - each of `passes`, a near miss, gets no finding from this rule.
// A rule needing a long example has a check or a steer that's too broad.

import type { Catalog } from '../catalog';
import { parsing } from './parsing';
import { shapes } from './shapes';
import { libraries } from './libraries';
import { errors } from './errors';
import { types } from './types';
import { names } from './names';
import { interfaces } from './interfaces';
import { dispatch } from './dispatch';
import { truncation } from './truncation';
import { comments } from './comments';
import { boundaries } from './boundaries';
import { collections } from './collections';
import { constants } from './constants';

export const rules = {
    ...parsing,
    ...shapes,
    ...libraries,
    ...errors,
    ...types,
    ...names,
    ...interfaces,
    ...dispatch,
    ...truncation,
    ...comments,
    ...boundaries,
    ...collections,
    ...constants,
} satisfies Catalog;
