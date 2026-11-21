// Dispatch: deciding on a value says what it decides on.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const dispatch = {
    elif: {
        category: 'spelling',
        mistake: 'An `elif` chain hides which value decides, arm after arm.',
        steer:
            "Decide on a value's structure with `match`; compare with guard clauses that return, one `if` " +
            'after another.',
        check(file) {
            for (const keyword of file.elifs()) {
                file.report(keyword, 'this is an `elif`');
            }
            for (const keyword of file.elseIfs()) {
                file.report(keyword, 'this `if` is all its `else` holds, an `elif` written out');
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            elif seconds < 3600:
                                return "m"
                            return "h"
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            if seconds < 3600:
                                return "m"
                            return "h"
                    `,
                },
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                unit = "s"
                            else:
                                if seconds < 3600:
                                    unit = "m"
                                else:
                                    unit = "h"
                            return unit
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            if seconds < 3600:
                                return "m"
                            return "h"
                    `,
                },
            ],
            passes: [
                python`
                    def sign(number: int) -> int:
                        """Return the sign of a number."""
                        if number < 0:
                            return -1
                        return 1 if number > 0 else 0
                `,
            ],
        },
    },

    'wildcard-guard': {
        category: 'spelling',
        mistake: 'A guard on a pattern that matches anything is an `if` chain dressed as a `match`.',
        steer:
            'Write a pattern that binds what the guard reads (`case Lease(reason=str() as reason) if reason:`), ' +
            'or compare with guard clauses.',
        check(file) {
            for (const guarded of file.guardedCases()) {
                if (guarded.irrefutable) {
                    file.report(guarded.range, `\`${file.text(guarded.range)}\` guards a pattern that matches anything`);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            match seconds:
                                case _ if seconds < 60:
                                    return "s"
                                case _:
                                    return "m"
                    `,
                    rewritten: python`
                        def unit(seconds: int) -> str:
                            """Return the unit a duration shows in."""
                            if seconds < 60:
                                return "s"
                            return "m"
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class Lease(Model):
                        """A hold on a resource, and why it's held."""

                        reason: str


                    def why(lease: Lease | None) -> str:
                        """Say why a lease is held, if it is."""
                        match lease:
                            case Lease(reason=str() as reason) if reason:
                                return reason
                            case _:
                                return "unheld"
                `,
            ],
        },
    },

    'isinstance-chain': {
        category: 'spelling',
        mistake: 'A chain of `isinstance` tests on one value hides that it decides on its class, arm after arm.',
        steer: 'Decide with a `match` on the value, a class pattern each arm: `case int():`.',
        check(file) {
            for (const chain of file.isinstanceChains()) {
                const [first, ...rest] = chain;
                for (const arm of rest) {
                    file.report(arm.node, `\`${arm.subject}\` was narrowed by \`isinstance\` in an arm before, at \`${file.text(first.node)}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def size(value: int | str | list[int]) -> int:
                            """Return how big a value is."""
                            if isinstance(value, int):
                                return value
                            if isinstance(value, str):
                                return len(value)
                            return len(value)
                    `,
                    rewritten: python`
                        def size(value: int | str | list[int]) -> int:
                            """Return how big a value is."""
                            match value:
                                case int():
                                    return value
                                case _:
                                    return len(value)
                    `,
                },
            ],
            passes: [
                python`
                    def size(value: int | str) -> int:
                        """Return how big a value is."""
                        if isinstance(value, int):
                            return value
                        return len(value)
                `,
            ],
        },
    },

    'own-model-dispatch': {
        category: 'design',
        mistake:
            'Choosing by which implementation of one of our ABCs you hold bypasses the seam the ABC is, and ' +
            'leaves the others to drift.',
        steer: 'Add a method to the ABC, which each implementation answers, and call it.',
        check(file) {
            for (const named of [...file.isinstanceClasses(), ...file.classPatterns()]) {
                const [implemented] = named.implements;
                if (implemented) {
                    file.report(named.node, `\`${file.text(named.node)}\` implements our ABC \`${implemented}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """An agent runtime."""

                            @abstractmethod
                            def name(self) -> str:
                                """Return the runtime's name."""


                        class Local(Runtime):
                            """A runtime on this machine."""

                            def name(self) -> str:
                                """Return the runtime's name."""
                                return "local"


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return isinstance(runtime, Local)
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """An agent runtime."""

                            @abstractmethod
                            def name(self) -> str:
                                """Return the runtime's name."""

                            @abstractmethod
                            def asks_before(self) -> bool:
                                """Say whether the runtime asks before a call runs."""


                        class Local(Runtime):
                            """A runtime on this machine."""

                            def name(self) -> str:
                                """Return the runtime's name."""
                                return "local"

                            def asks_before(self) -> bool:
                                """Say whether the runtime asks before a call runs: it does."""
                                return True


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime.asks_before()
                    `,
                },
            ],
            passes: [
                python`
                    from abc import ABC, abstractmethod


                    class Runtime(ABC):
                        """An agent runtime."""

                        @abstractmethod
                        def name(self) -> str:
                            """Return the runtime's name."""


                    def named(value: Runtime | str) -> str:
                        """Return a runtime's name, or a name given as it is."""
                        return value.name() if isinstance(value, Runtime) else value
                `,
            ],
        },
    },
} satisfies Catalog;
