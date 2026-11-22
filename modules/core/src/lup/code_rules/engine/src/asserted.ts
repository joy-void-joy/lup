// What a test's `assert`s compare, for the rules about tests (`rules/tests.ts`): where
// each side comes from, followed through the names it's bound to and the functions
// returning it, a few steps at most.

import { DeclarationType } from 'pyright/analyzer/declaration';
import { ComprehensionNode, ExpressionNode, isExpressionNode, ListNode, ParseNodeType } from 'pyright/parser/parseNodes';

import { Asserted, File, keepsText } from './file';

// How many names and calls a side is followed through.
const reach = 3;

// What a promise starts, which hears each run of a program it stands in for, and one
// run as it heard it (`lup.testing`).
const started = 'lup.testing.harness.Started';
const programRun = 'lup.testing.harness.ProgramRun';

// What a call through a door answers, and why one is refused (`lup.doors`).
const answers = ['lup.doors.door.Accepted', 'lup.doors.door.Refused'];
const rejection = 'lup.doors.door.Rejection';

// Calls answering what they're given, or a copy of it: `json.loads(answer)`,
// `sorted(names)`.
const keeping = ['json.loads', 'builtins.list', 'builtins.sorted', 'builtins.set', 'builtins.dict'];

// The sides of a comparison, as pairs to read: for `contains`, what's looked for and
// where; for `equals`, each side with the other.
export function sides(compared: Asserted): [ExpressionNode, ExpressionNode][] {
    const { left, right } = compared;
    return compared.kind === 'contains'
        ? [[left, right]]
        : [
              [left, right],
              [right, left],
          ];
}

// What a stand-in for a part's programs heard that an expression holds: `runs`, the
// arguments of each run (`started.ran("git")`, a slice of it, a comprehension keeping
// some, a function returning them); `arguments`, one run's (`run.arguments`, an item
// of `runs`). None for anything else.
export function heard(file: File, node: ExpressionNode, depth = 0): 'runs' | 'arguments' | undefined {
    if (depth > reach) {
        return undefined;
    }
    switch (node.nodeType) {
        case ParseNodeType.Call: {
            const callee = node.d.leftExpr;
            const ran =
                callee.nodeType === ParseNodeType.MemberAccess &&
                callee.d.member.d.value === 'ran' &&
                file.isInstance(callee.d.leftExpr, [started]);
            return ran ? 'runs' : agreed(returned(file, callee).map((each) => heard(file, each, depth + 1)));
        }
        case ParseNodeType.MemberAccess:
            return node.d.member.d.value === 'arguments' && file.isInstance(node.d.leftExpr, [programRun])
                ? 'arguments'
                : undefined;
        case ParseNodeType.Index: {
            if (heard(file, node.d.leftExpr, depth) !== 'runs') {
                return undefined;
            }
            const sliced = node.d.items.length === 1 && node.d.items[0].d.valueExpr.nodeType === ParseNodeType.Slice;
            return sliced ? 'runs' : 'arguments';
        }
        case ParseNodeType.List: {
            const kept = comprehended(node)?.d.expr;
            return kept && isExpressionNode(kept) && heard(file, kept, depth) === 'arguments' ? 'runs' : undefined;
        }
        case ParseNodeType.Name:
            return agreed(
                (file.boundTo(node) ?? []).map(({ node: bound, item }) => {
                    const kind = heard(file, bound, depth + 1);
                    if (!item) {
                        return kind;
                    }
                    return kind === 'runs' ? 'arguments' : undefined;
                })
            );
        default:
            return undefined;
    }
}

// Whether an expression holds what a call through a door answered, or a part of it: an
// `Accepted` or a `Refused`, what's read off it, parsed from it (`json.loads(…)`), or
// kept of it by a comprehension.
export function answered(file: File, node: ExpressionNode, depth = 0): boolean {
    if (file.isInstance(node, answers)) {
        return true;
    }
    if (depth > reach) {
        return false;
    }
    switch (node.nodeType) {
        case ParseNodeType.MemberAccess:
        case ParseNodeType.Index:
            return answered(file, node.d.leftExpr, depth);
        case ParseNodeType.Await:
            return answered(file, node.d.expr, depth);
        case ParseNodeType.Call: {
            const callee = node.d.leftExpr;
            const [first] = node.d.args;
            if (file.namesOf(callee).some((name) => keeping.includes(name))) {
                return first !== undefined && answered(file, first.d.valueExpr, depth);
            }
            return callee.nodeType === ParseNodeType.MemberAccess && answered(file, callee.d.leftExpr, depth);
        }
        case ParseNodeType.List: {
            const [source] = comprehended(node)?.d.forIfNodes ?? [];
            return source?.nodeType === ParseNodeType.ComprehensionFor && answered(file, source.d.iterableExpr, depth);
        }
        case ParseNodeType.Name: {
            const bound = file.boundTo(node);
            return bound !== undefined && bound.every((each) => answered(file, each.node, depth + 1));
        }
        default:
            return false;
    }
}

// Whether an expression is the reason a call was refused, as it is or through a method
// keeping it text: `refused.rejection.reason`, `reason.lower()`.
export function isReason(file: File, node: ExpressionNode, depth = 0): boolean {
    if (depth > reach) {
        return false;
    }
    switch (node.nodeType) {
        case ParseNodeType.MemberAccess:
            return node.d.member.d.value === 'reason' && file.isInstance(node.d.leftExpr, [rejection]);
        case ParseNodeType.Call: {
            const callee = node.d.leftExpr;
            return (
                callee.nodeType === ParseNodeType.MemberAccess &&
                keepsText.includes(callee.d.member.d.value) &&
                isReason(file, callee.d.leftExpr, depth)
            );
        }
        case ParseNodeType.Name: {
            const bound = file.boundTo(node);
            return bound !== undefined && bound.every((each) => !each.item && isReason(file, each.node, depth + 1));
        }
        default:
            return false;
    }
}

// Whether an expression writes a collection out, holding something: a list, a set or a
// dict display rather than a comprehension, or a conditional either branch of which is
// one.
export function writesCollection(node: ExpressionNode): boolean {
    switch (node.nodeType) {
        case ParseNodeType.List:
        case ParseNodeType.Set:
            return node.d.items.length > 0 && node.d.items.every((item) => item.nodeType !== ParseNodeType.Comprehension);
        case ParseNodeType.Dictionary:
            return node.d.items.length > 0 && node.d.items.every((item) => item.nodeType !== ParseNodeType.Comprehension);
        case ParseNodeType.Ternary:
            return writesCollection(node.d.ifExpr) || writesCollection(node.d.elseExpr);
        default:
            return false;
    }
}

// Whether an expression writes a list out, holding something, or names one bound to it
// alone: `["-C", path, "init"]`, `clearing` after `clearing = ["stop", …]`.
export function writesList(file: File, node: ExpressionNode): boolean {
    if (node.nodeType === ParseNodeType.List) {
        return writesCollection(node);
    }
    if (node.nodeType !== ParseNodeType.Name) {
        return false;
    }
    const bound = file.boundTo(node);
    return bound !== undefined && bound.every((each) => !each.item && each.node.nodeType === ParseNodeType.List && writesCollection(each.node));
}

// Whether a string reads as words: two runs of text a space parts.
export function isProse(text: string): boolean {
    return /\S\s+\S/.test(text);
}

// Whether a test wrote `text` itself: within a string it writes as data, or as the
// first line of a docstring, a stand-in's that it reads back.
export function writtenByTheTest(file: File, text: string): boolean {
    return (
        file.writtenOutsideAsserts().some((each) => each.includes(text)) ||
        file.docstrings().some((each) => each.text.split('\n')[0].trim() === text.trim())
    );
}

// The comprehension a list display holds, where it's one: `[each for each in runs]`.
function comprehended(node: ListNode): ComprehensionNode | undefined {
    const [only, ...more] = node.d.items;
    return only?.nodeType === ParseNodeType.Comprehension && more.length === 0 ? only : undefined;
}

// The expressions the functions a callee names return, each `return`'s: what a helper
// such as `podman_ran(started, "run")` answers.
function returned(file: File, callee: ExpressionNode): ExpressionNode[] {
    const name =
        callee.nodeType === ParseNodeType.Name
            ? callee
            : callee.nodeType === ParseNodeType.MemberAccess
            ? callee.d.member
            : undefined;
    const declarations = name ? file.evaluator.getDeclInfoForNameNode(name)?.decls ?? [] : [];
    return declarations.flatMap((declaration) => {
        const resolved = file.evaluator.resolveAliasDeclaration(declaration, /* resolveLocalNames */ true);
        if (resolved?.type !== DeclarationType.Function) {
            return [];
        }
        return (resolved.returnStatements ?? []).flatMap((statement) => (statement.d.expr ? [statement.d.expr] : []));
    });
}

// The one value every item holds, where there's at least one; none where they differ.
function agreed<T>(items: (T | undefined)[]): T | undefined {
    const [first] = items;
    return items.every((each) => each === first) ? first : undefined;
}
