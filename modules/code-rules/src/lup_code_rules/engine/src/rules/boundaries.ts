// Boundaries: code above the runtimes' adapter speaks in lup's own words.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const boundaries = {
    'runtime-mention': {
        category: 'design',
        mistake:
            'A runtime named outside its adapter builds a feature for one runtime above the seam, where the others ' +
            'quietly lack it.',
        steer:
            "Speak in lup's own words and capabilities (`runtime.inside()`); the runtime's spelling, and the " +
            'evidence behind a capability, belong in its adapter.',
        check(file) {
            for (const mention of file.mentionsOf(['claude', 'codex'])) {
                if (`.${file.moduleName}.`.includes(`.adapters.${mention.name}.`)) {
                    continue;
                }
                file.report(
                    mention.range,
                    mention.kind === 'name'
                        ? `\`${file.text(mention.range)}\` holds a runtime's name, \`${mention.name}\``
                        : `this ${mention.kind} names a runtime, \`${mention.name}\``
                );
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def asks_first(runtime: str) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime == "claude"
                    `,
                    rewritten: python`
                        from abc import ABC, abstractmethod


                        class Runtime(ABC):
                            """One agent runtime, as lup sees it."""

                            @abstractmethod
                            def asks_before(self) -> bool:
                                """Say whether the runtime can ask the operator before a call runs."""


                        def asks_first(runtime: Runtime) -> bool:
                            """Say whether a runtime asks before a call runs."""
                            return runtime.asks_before()
                    `,
                },
            ],
            passes: [
                python`
                    def settings_home(name: str) -> str:
                        """Return where a runtime keeps its settings, by the name its adapter gives."""
                        return f".{name}"
                `,
            ],
        },
    },
} satisfies Catalog;
