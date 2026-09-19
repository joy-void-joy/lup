<!-- section: First Setup -->
## First Setup

**[IMPORTANT: Run `uv run lup-devtools sync mark-synced lup` to initialize upstream sync tracking, then delete this section.]**

<!-- section: Project Overview -->
## Project Overview

**[Describe your agent and what it does]**

Built with Python 3.14+ on the Claude Agent SDK, with the inner agent also runnable on the OpenAI Codex SDK (`AGENT_SDK=codex`) or any OpenAI-compatible endpoint (`AGENT_SDK=openai`) through the same adapter interface. Uses `uv` as the package manager.

The security envelope is capability-specific: Claude uses normalized SDK hooks
plus its sandbox and permission mode; Codex uses generated command hooks where
the installed CLI supports them plus its workspace sandbox. Unsupported
approval effects fail closed and are recorded as explicit capability gaps.

Every supported runtime must provide equivalent user-visible behavior, validation, diagnostics, tests, and documentation for each capability. Runtime-specific implementations are valid only when their semantic differences are explicit and evidence-backed.

### Naming Convention

