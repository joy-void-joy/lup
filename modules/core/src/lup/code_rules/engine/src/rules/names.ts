// Names: a name is public or nested, and a package's root says what it exports.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const names = {
    'all-export': {
        category: 'design',
        mistake:
            "`__all__` outside a package's root makes a second public list, beside the one the package's root " +
            'declares.',
        steer: "Leave `__all__` to the package's root; elsewhere, import each name from the module that defines it.",
        check(file) {
            if (file.isPackageRoot) {
                return;
            }
            for (const assigned of file.moduleAssignments()) {
                if (assigned.name === '__all__') {
                    file.report(assigned.node, "this module isn't a package's root");
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        __all__ = ["greet"]


                        def greet() -> str:
                            """Return a greeting."""
                            return "hello"
                    `,
                    rewritten: python`
                        def greet() -> str:
                            """Return a greeting."""
                            return "hello"
                    `,
                },
            ],
            passes: [
                python`
                    import json


                    def exported() -> list[str]:
                        """List what \`json\` exports."""
                        return list(json.__all__)
                `,
            ],
        },
    },

    'private-name': {
        category: 'design',
        mistake: 'A leading underscore is a second kind of visibility, beside public, that a reviewer has to second-guess.',
        steer:
            'Make the name public, or nest a helper inside its only caller; inline a wrapper around one call. An ' +
            'unused parameter keeps its underscore.',
        check(file) {
            if (file.isPrivateModule) {
                file.report({ start: 0, length: 0 }, "the module's own name is private");
            }
            for (const binding of file.privateNames()) {
                file.report(binding.node, `\`${binding.name}\` is private`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def _cleaned(text: str) -> str:
                            return text.strip()


                        def words(text: str) -> list[str]:
                            """Split text into its words."""
                            return _cleaned(text).split()
                    `,
                    rewritten: python`
                        def words(text: str) -> list[str]:
                            """Split text into its words."""
                            return text.strip().split()
                    `,
                },
            ],
            passes: [
                python`
                    def count(values: list[int], _reason: str = "") -> int:
                        """Count the values; the reason is for the caller's records."""
                        return sum(1 for _ in values)
                `,
            ],
        },
    },
} satisfies Catalog;
