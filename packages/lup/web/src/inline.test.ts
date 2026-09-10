// The inline-safe plugin: what it escapes, what it refuses, the template it
// emits, and one real build proving the escapes survive minification and
// the stylesheet's rewrite reaches the disk.
import { mkdtempSync, readdirSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { expect, test } from "bun:test";
import { build } from "vite";
import { escapedScript, escapedStyle, exportTemplate, inlineSafe } from "../vite.config";

const PAGE = `<!doctype html>
<html lang="en">
  <head>
    <title>Fixture</title>
    <script type="module" crossorigin src="./assets/index-1.js"></script>
    <link rel="stylesheet" crossorigin href="./assets/index-1.css">
  </head>
  <body>
    <div id="root"></div>
  </body>
</html>
`;

test("enders inside literals are escaped, whatever their case, and the script parses as it did", () => {
  const code = 'const a = "</SCRIPT>"; const b = "<!--"; export const seen = [a, b, `</script>`, /<!--/];\n';

  expect(escapedScript(code, "app.js")).toBe(
    'const a = "<\\/SCRIPT>"; const b = "<\\!--"; export const seen = [a, b, `<\\/script>`, /<\\!--/];\n',
  );
});

test("an ender outside a literal fails naming the file and the line", () => {
  // `x</script>/.test(y)` is JavaScript — `x < /script>/.test(y)` — and its
  // escape is not, so the parse refuses the file where the escape landed.
  let message = "";
  try {
    escapedScript("const y = 's';\nconst z = x</script>/.test(y);\n", "app.js");
  } catch (failure) {
    message = failure instanceof Error ? failure.message : String(failure);
  }

  expect(message).toContain("app.js does not parse once escaped for inlining");
  expect(message).toContain("2: const z = x<\\/script>/.test(y);");
  expect(message).toContain("Unterminated regular expression");
});

test("a stylesheet's ender is escaped, whatever its case", () => {
  expect(escapedStyle('body::after{content:"</STYLE>"}\n')).toBe('body::after{content:"<\\/STYLE>"}\n');
});

test("the export template is the page with the bundle inline and the mount carrying the log", () => {
  const script = { fileName: "assets/index-1.js", text: 'const t = "{{ not jinja }} {# nor this #} $& $1";\n' };
  const style = { fileName: "assets/index-1.css", text: "body{margin:0}\n" };

  const template = exportTemplate(PAGE, [script], [style]);

  expect(template).toContain(`<script type="module">{% raw %}${script.text}{% endraw %}</script>`);
  expect(template).toContain(`<style>{% raw %}${style.text}{% endraw %}</style>`);
  expect(template).toContain('<div id="root" data-lup-export="{{ log }}"></div>');
  expect(template).not.toContain("src=");
  expect(template).not.toContain("href=");
  expect(() => exportTemplate(PAGE, [{ fileName: "assets/other.js", text: "" }], [style])).toThrow(/assets\/other\.js/);
  expect(() => exportTemplate(PAGE, [{ ...script, text: "{% endraw %}" }], [style])).toThrow(/raw block/);
});

test("a build lands the escaped script and stylesheet and the template beside the page", async () => {
  const root = mkdtempSync(join(tmpdir(), "lup-inline-"));
  writeFileSync(
    join(root, "index.html"),
    '<!doctype html><html><head><script type="module" src="./main.js"></script></head>' +
      '<body><div id="root"></div></body></html>\n',
  );
  writeFileSync(
    join(root, "main.js"),
    'import "./style.css";\nexport const seen = ["</script>", "<!--", `</SCRIPT>`];\n' +
      'document.body.textContent = seen.join(" ");\n',
  );
  writeFileSync(join(root, "style.css"), 'body::after{content:"</style>"}\n');
  const outDir = join(root, "out");

  await build({
    root,
    configFile: false,
    logLevel: "silent",
    base: "./",
    plugins: [inlineSafe(true)],
    build: { outDir, emptyOutDir: true, rollupOptions: { output: { inlineDynamicImports: true } } },
  });

  const assets = readdirSync(join(outDir, "assets"));
  const script = readFileSync(join(outDir, "assets", assets.find((name) => name.endsWith(".js")) ?? ""), "utf8");
  const style = readFileSync(join(outDir, "assets", assets.find((name) => name.endsWith(".css")) ?? ""), "utf8");
  const template = readFileSync(join(outDir, "export.html.j2"), "utf8");
  const page = readFileSync(join(outDir, "index.html"), "utf8");
  expect(script).not.toMatch(/<\/script|<!--/i);
  expect(script).toContain("<\\/script>");
  expect(script).toContain("<\\!--");
  expect(style).toContain('"<\\/style>"');
  expect(template).toContain(`<script type="module">{% raw %}${script}{% endraw %}</script>`);
  expect(template).toContain(`<style>{% raw %}${style}{% endraw %}</style>`);
  expect(template).toContain('<div id="root" data-lup-export="{{ log }}"></div>');
  expect(page).not.toContain("{{");
  expect(page).toContain('<div id="root"></div>');
});
