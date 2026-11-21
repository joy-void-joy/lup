// What the rules ask pyright about a node, defined once for every helper that reads
// types: an expression's type member by member, what a type expression denotes, and
// what a name resolves to.

import { DeclarationType } from 'pyright/analyzer/declaration';
import { Program } from 'pyright/analyzer/program';
import { isUserCode } from 'pyright/analyzer/sourceFileInfoUtils';
import { TypeEvaluator } from 'pyright/analyzer/typeEvaluatorTypes';
import { ClassType, isAny, isClassInstance, isInstantiableClass, isModule, isUnknown, Type } from 'pyright/analyzer/types';
import { doForEachSubtype, isNoneInstance } from 'pyright/analyzer/typeUtils';
import { ExpressionNode, ParseNode, ParseNodeType } from 'pyright/parser/parseNodes';

export interface Member {
    kind: 'class' | 'any' | 'unknown' | 'none' | 'other';
    printed: string;
    class: string | null;
    typedDict: boolean;
    // Which of the classes asked about pyright finds this member assignable to.
    assignableTo: string[];
}

// The type of an expression, member by member, with pyright deciding for each member
// whether it's assignable to each of `classes`. `Any` is a declared `Any`; a type
// pyright can't infer is `unknown`.
export function describeType(evaluator: TypeEvaluator, node: ExpressionNode, classes: string[]): Member[] {
    const type = evaluator.getType(node);
    if (!type) {
        return [{ kind: 'unknown', printed: '<no type>', class: null, typedDict: false, assignableTo: [] }];
    }
    const targets = classes.map((name) => ({ name, type: classNamed(evaluator, node, name) }));
    const members: Member[] = [];
    doForEachSubtype(evaluator.makeTopLevelTypeVarsConcrete(type), (subtype: Type) => {
        const member = { printed: evaluator.printType(subtype), class: null, typedDict: false, assignableTo: [] };
        if (isUnknown(subtype)) {
            members.push({ ...member, kind: 'unknown' });
            return;
        }
        if (isAny(subtype)) {
            members.push({ ...member, kind: 'any' });
            return;
        }
        if (isNoneInstance(subtype)) {
            members.push({ ...member, kind: 'none' });
            return;
        }
        if (isClassInstance(subtype)) {
            members.push({
                ...member,
                kind: 'class',
                class: subtype.shared.fullName,
                typedDict: ClassType.isTypedDictClass(subtype),
                assignableTo: targets
                    .filter((target) => evaluator.assignType(ClassType.cloneAsInstance(target.type), subtype))
                    .map((target) => target.name),
            });
            return;
        }
        members.push({ ...member, kind: 'other' });
    });
    return members;
}

// A class from `builtins` or `typing`, by its fully qualified name: the two modules
// whose classes the rules name.
function classNamed(evaluator: TypeEvaluator, node: ParseNode, fullName: string): ClassType {
    const dot = fullName.lastIndexOf('.');
    const module = fullName.substring(0, dot);
    const name = fullName.substring(dot + 1);
    const type =
        module === 'builtins'
            ? evaluator.getBuiltInType(node, name)
            : module === 'typing'
            ? evaluator.getTypingType(node, name)
            : undefined;
    if (!type || !isInstantiableClass(type)) {
        throw new Error(`no class named ${fullName}: the rules name classes from builtins and typing`);
    }
    return type;
}

export interface Meaning {
    // The class the expression names, when it names one as a type.
    class: string | null;
    // The alias the expression names, when it names one.
    alias: { name: string; inProject: boolean } | null;
    // Whether the class already has its type arguments (`tuple[int, str]`).
    hasTypeArgs: boolean;
}

// What a type expression denotes, aliases included.
export function denotes(program: Program, evaluator: TypeEvaluator, node: ExpressionNode): Meaning {
    const type = evaluator.getType(node);
    if (!type || !isInstantiableClass(type)) {
        return { class: null, alias: null, hasTypeArgs: false };
    }
    const aliasInfo = type.props?.typeAliasInfo;
    const alias = aliasInfo
        ? { name: aliasInfo.shared.name, inProject: isUserCode(program.getSourceFileInfo(aliasInfo.shared.fileUri)) }
        : null;
    return {
        class: type.shared.fullName,
        alias,
        hasTypeArgs: type.priv.tupleTypeArgs !== undefined || (type.priv.typeArgs?.length ?? 0) > 0,
    };
}

// The fully qualified names a reference resolves to, following imports; a module
// resolves to its own name, from its file, since pyright names a module by how it
// was imported (`os` brings in `path` as `..path`).
export function resolve(program: Program, evaluator: TypeEvaluator, node: ExpressionNode): string[] {
    const type = evaluator.getType(node);
    if (type && isModule(type)) {
        const module = program.getSourceFile(type.priv.fileUri)?.getModuleName();
        return [module || type.priv.moduleName];
    }
    const name =
        node.nodeType === ParseNodeType.Name
            ? node
            : node.nodeType === ParseNodeType.MemberAccess
            ? node.d.member
            : undefined;
    if (!name) {
        return [];
    }
    return (evaluator.getDeclInfoForNameNode(name)?.decls ?? []).flatMap((declaration) => {
        const resolved = evaluator.resolveAliasDeclaration(declaration, /* resolveLocalNames */ true);
        if (!resolved) {
            return [];
        }
        switch (resolved.type) {
            case DeclarationType.Variable:
                return resolved.node.nodeType === ParseNodeType.Name
                    ? [`${resolved.moduleName}.${resolved.node.d.value}`]
                    : [];
            case DeclarationType.Function:
            case DeclarationType.Class:
            case DeclarationType.TypeAlias:
                return [`${resolved.moduleName}.${resolved.node.d.name.d.value}`];
            case DeclarationType.SpecialBuiltInClass:
                return resolved.node.d.valueExpr.nodeType === ParseNodeType.Name
                    ? [`${resolved.moduleName}.${resolved.node.d.valueExpr.d.value}`]
                    : [];
            default:
                return [];
        }
    });
}
