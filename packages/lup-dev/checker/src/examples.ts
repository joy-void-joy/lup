// Writing a rule's examples in the table (`lup_dev/catalog/rules.ts`) as indented
// blocks: `python` takes a template literal and returns the code with the indentation
// its lines share removed, without its first and last blank lines.

export function python(strings: TemplateStringsArray, ...values: unknown[]): string {
    const written = strings.reduce((code, part, index) => code + part + (index < values.length ? String(values[index]) : ''), '');
    const lines = written.split('\n');
    while (lines.length > 0 && lines[0].trim() === '') {
        lines.shift();
    }
    while (lines.length > 0 && lines[lines.length - 1].trim() === '') {
        lines.pop();
    }
    const indents = lines.filter((line) => line.trim() !== '').map((line) => line.length - line.trimStart().length);
    const shared = indents.length > 0 ? Math.min(...indents) : 0;
    return lines.map((line) => line.substring(shared)).join('\n') + '\n';
}
