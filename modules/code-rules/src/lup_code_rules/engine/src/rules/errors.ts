// Errors: raise what can't be recovered, under the package's root error, and never swallow one.

import type { Catalog } from '../catalog';
import { python } from '../examples';

export const errors = {
    suppress: {
        category: 'design',
        mistake: 'An error swallowed by `suppress` leaves no trace of what failed, or why.',
        steer: 'Handle the error, log it, or let it rise; where a library can skip the case itself, let it.',
        check(file) {
            for (const used of file.uses(['contextlib.suppress'])) {
                file.report(used.node, `this uses \`${used.name}\``);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from contextlib import suppress
                        from pathlib import Path


                        def remove(path: str) -> None:
                            """Remove a file, if it's there."""
                            with suppress(FileNotFoundError):
                                Path(path).unlink()
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def remove(path: str) -> None:
                            """Remove a file, if it's there."""
                            Path(path).unlink(missing_ok=True)
                    `,
                },
            ],
            passes: [
                python`
                    from contextlib import ExitStack


                    def stack() -> ExitStack:
                        """Return an empty stack of exits."""
                        return ExitStack()
                `,
            ],
        },
    },

    'bare-except': {
        category: 'design',
        mistake: 'A bare `except:` catches everything, `KeyboardInterrupt` and `SystemExit` included, and hides why.',
        steer: 'Catch `Exception` or something narrower, and handle, log or re-raise it.',
        check(file) {
            for (const clause of file.exceptClauses()) {
                if (!clause.d.typeExpr) {
                    file.report(clause.d.exceptToken, 'this `except:` names nothing to catch');
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except:
                                return 0
                    `,
                    rewritten: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except ValueError:
                                return 0
                    `,
                },
            ],
            passes: [
                python`
                    def number(text: str) -> int:
                        """Read a number, or zero."""
                        try:
                            return int(text)
                        except (ValueError, OverflowError):
                            return 0
                `,
            ],
        },
    },

    'except-baseexception': {
        category: 'design',
        mistake: 'Catching `BaseException` catches `KeyboardInterrupt` and `SystemExit` too, so nothing can stop the code.',
        steer: 'Catch `Exception` or something narrower, and handle, log or re-raise it.',
        check(file) {
            for (const clause of file.exceptClauses()) {
                for (const caught of file.caught(clause)) {
                    if (caught.class === 'builtins.BaseException') {
                        file.report(caught.node, 'this clause catches `BaseException`');
                    }
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except BaseException:
                                return 0
                    `,
                    rewritten: python`
                        def number(text: str) -> int:
                            """Read a number, or zero."""
                            try:
                                return int(text)
                            except ValueError:
                                return 0
                    `,
                },
            ],
            passes: [
                python`
                    def wait() -> None:
                        """Wait until interrupted."""
                        try:
                            input()
                        except KeyboardInterrupt:
                            return
                `,
            ],
        },
    },

    'suppression-comment': {
        category: 'design',
        mistake: 'A second suppression syntax hides a finding without the operator ever being asked.',
        steer: 'Keep one finding with `# lup: ignore("<rule>", why="<reason>")`, which asks the operator.',
        check(file) {
            const markers = [
                'noqa',
                'type: ignore',
                'pyright: ignore',
                'pyright: basic',
                'pyright: standard',
                'pyright: report',
                'ruff: noqa',
                'ruff: disable',
            ];
            for (const comment of file.commentsStartingWith(markers)) {
                file.report(comment.range, `\`# ${comment.text}\` is a suppression comment`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        def width() -> int:
                            """Return the width."""
                            return 1  # noqa: PLR2004
                    `,
                    rewritten: python`
                        def width() -> int:
                            """Return the width."""
                            return 1
                    `,
                },
                {
                    code: python`
                        def width() -> int:
                            """Return the width."""
                            return "1"  # type: ignore[return-value]
                    `,
                    rewritten: python`
                        def width() -> int:
                            """Return the width."""
                            return 1
                    `,
                },
            ],
            passes: [
                python`
                    def width() -> int:
                        """Return the width."""
                        # the type checker reads this
                        return 1
                `,
            ],
        },
    },

    'error-root': {
        category: 'design',
        mistake: 'An exception outside its package\'s root error escapes a caller catching everything the package raises.',
        steer:
            "Derive it from the package's root error, named for the package (`LupDevError` in `lup_dev`), or from " +
            'an error below it.',
        check(file) {
            const root = file.packageRootError;
            for (const declared of file.classes()) {
                const name = declared.node.d.name.d.value;
                if (!declared.ancestors.includes('builtins.BaseException') || name === root) {
                    continue;
                }
                const rooted = declared.ancestors.some(
                    (ancestor) => ancestor.startsWith(`${file.packageName}.`) && ancestor.endsWith(`.${root}`)
                );
                if (!rooted) {
                    file.report(declared.node.d.name, `\`${name}\` doesn't descend from \`${root}\``);
                }
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        class ParseError(ValueError):
                            """The text isn't in the format."""
                    `,
                    rewritten: python`
                        class ExampleError(Exception):
                            """Anything this package raises."""


                        class ParseError(ExampleError):
                            """The text isn't in the format."""
                    `,
                },
            ],
            passes: [
                python`
                    from lup.types import Model


                    class ErrorReport(Model):
                        """What went wrong, as a person reads it."""

                        summary: str
                `,
            ],
        },
    },

    'error-text': {
        category: 'design',
        mistake: "Deciding on an exception's message breaks quietly when the message is reworded.",
        steer: "Decide on the exception's type, or on its structured fields (`errno`, `status_code`).",
        check(file) {
            for (const used of file.exceptionTexts()) {
                file.report(used.node, `\`${used.text}\` decides on an exception's message`);
            }
        },
        examples: {
            flags: [
                {
                    code: python`
                        from pathlib import Path


                        def removed(path: str) -> bool:
                            """Remove a file, saying whether it was there."""
                            try:
                                Path(path).unlink()
                            except OSError as error:
                                if "No such file" in str(error):
                                    return False
                                raise
                            return True
                    `,
                    rewritten: python`
                        from pathlib import Path


                        def removed(path: str) -> bool:
                            """Remove a file, saying whether it was there."""
                            try:
                                Path(path).unlink()
                            except FileNotFoundError:
                                return False
                            return True
                    `,
                },
            ],
            passes: [
                python`
                    def described(error: Exception) -> str:
                        """Describe an error for a person to read."""
                        return f"failed: {error}"
                `,
            ],
        },
    },
} satisfies Catalog;
