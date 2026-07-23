# Setup dashboard

`uv run lup-devtools dashboard` hosts a local browser interface at
`http://127.0.0.1:8765`. It is the web surface of the same declarative
integration registry used by `uv run lup-devtools setup`; domains customize
`INTEGRATIONS` once and get both interfaces.

The design distills the reusable setup patterns from Assistant and Inkwell:

- a progress-oriented wizard for first setup and an all-integrations view for
  later maintenance;
- status and writes served by a thin API over the CLI's setup functions;
- browser forms only for declarative env fields, with bespoke OAuth or
  validation workflows routed to their existing CLI command;
- an explicit field allowlist derived from each integration, so the browser
  cannot write arbitrary environment variables.

The dashboard is deliberately local and zero-build. FastAPI serves one
packaged HTML asset; downstream projects do not need Node merely to customize
their setup registry. Run with `--no-open`, `--host`, or `--port` when the
default browser behavior or bind address is unsuitable.
