// Docstrings and comments: they say what is, in one markup.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const comments = {
    'historical-voice': {
        category: 'heuristic',
        mistake: 'A comment or docstring telling how the code came to be means something only against a version the reader never sees.',
        steer:
            'Say what is: "the call waits", not "the call now waits"; "the parser", not "the new parser". ' +
            'History belongs in the commit message.',
        check(file) {
            // Each word is read beside its neighbours in its phrase, since most of them also
            // name a moment or a thing of the running code: "for now", "a new reply" and
            // "fixed for its life" tell nothing of the code's past.
            const always = ['previously', 'formerly', 'anymore'];
            // `now` names a moment of the running code after these, or before `that` or `on`.
            const moment = ['for', 'right', 'from', 'just', 'by', 'until'];
            // `new` and `newly` set a thing against what it replaced after these; after
            // `a` they name an instance the code makes.
            const against = ['the', 'this', 'these', 'our'];
            // `fixed` tells of a repair after these, or before what was repaired.
            const done = ['was', 'were', 'been', 'is', 'are', 'has', 'have', 'had', 'got', 'gets'];
            const repaired = ['a', 'an', 'the', 'this', 'that', 'these', 'those', 'its', 'their', 'bug', 'bugs'];
            for (const prose of file.prose()) {
                for (const phrase of file.phrases(prose)) {
                    phrase.forEach((word, index) => {
                        const before = phrase[index - 1]?.text ?? '';
                        const after = phrase[index + 1]?.text ?? '';
                        const said =
                            (always.includes(word.text) && word.text) ||
                            (word.text === 'no' && after === 'longer' && 'no longer') ||
                            (word.text === 'now' && !moment.includes(before) && !['that', 'on'].includes(after) && 'now') ||
                            (['new', 'newly'].includes(word.text) && against.includes(before) && word.text) ||
                            (word.text === 'fixed' && (done.includes(before) || repaired.includes(after)) && 'fixed');
                        if (said) {
                            file.report(word.range, `"${said}" tells how the code came to be`);
                        }
                    });
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        import time


                        def pause(seconds: float) -> None:
                            """Pause before the next try, which now waits a second at least."""
                            time.sleep(max(seconds, 1))
                    `,
                    rewritten: python`
                        import time


                        def pause(seconds: float) -> None:
                            """Pause before the next try, for a second at least."""
                            time.sleep(max(seconds, 1))
                    `,
                },
                {
                    code: python`
                        def field(record: dict[str, str], name: str) -> str | None:
                            """Read one field of a record: a missing one no longer raises."""
                            return record.get(name)
                    `,
                    rewritten: python`
                        def field(record: dict[str, str], name: str) -> str | None:
                            """Read one field of a record: none where it's missing."""
                            return record.get(name)
                    `,
                },
                {
                    code: python`
                        def width(text: str) -> int:
                            """Count the columns a line takes, with the new parser."""
                            return len(text.expandtabs())
                    `,
                    rewritten: python`
                        def width(text: str) -> int:
                            """Count the columns a line takes, tabs expanded."""
                            return len(text.expandtabs())
                    `,
                },
                {
                    code: python`
                        def joined(lines: list[str]) -> str:
                            """Join lines, which fixed the trailing newline."""
                            return "\\n".join(lines)
                    `,
                    rewritten: python`
                        def joined(lines: list[str]) -> str:
                            """Join lines, with no newline after the last."""
                            return "\\n".join(lines)
                    `,
                },
            ],
            passes: [
                python`
                    def described(old: str, replacement: str) -> str:
                        """Describe an edit: its \`old_string\` and \`new_string\`, which "the new text" names."""
                        return f"{old} -> {replacement}"
                `,
                python`
                    def reply(draft: str) -> str:
                        """Send what's drafted as a new reply, from now on to every agent; for now, the draft is kept as written."""
                        return draft
                `,
                python`
                    def tools(names: list[str]) -> list[str]:
                        """List a thread's tools, fixed for its life: a fixed set, since right now the lock is held, and now that it is, nothing changes them."""
                        return sorted(names)
                `,
                python`
                    def lifted(held: list[str]) -> list[str]:
                        """Lift a hold, returning the findings it kept back until now."""
                        return held
                `,
            ],
        },
    },

    'docstring-code': {
        category: 'spelling',
        mistake: "reStructuredText's double backticks and Sphinx roles are a second way to mark code, beside Markdown's.",
        steer: 'Mark inline code with single backticks: `name`, `print`.',
        check(file) {
            for (const docstring of file.docstrings()) {
                for (const mark of file.codeMarks(docstring)) {
                    file.report(
                        mark.range,
                        mark.written === '``' ? 'this marks code with double backticks' : `\`${mark.written}\` is a Sphinx role`
                    );
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def greet(name: str) -> str:
                            """Return a greeting for \`\`name\`\`; see :func:\`print\`."""
                            return f"hello {name}"
                    `,
                    rewritten: python`
                        def greet(name: str) -> str:
                            """Return a greeting for \`name\`; see \`print\`."""
                            return f"hello {name}"
                    `,
                },
            ],
            passes: [
                python`
                    def greet(name: str) -> str:
                        """Return a greeting. Usage: \`greet("Ada")\`."""
                        return f"hello {name}"
                `,
            ],
        },
    },
} satisfies Catalog;
