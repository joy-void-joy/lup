| `docs/` | rendered by the Claude recipe | none | Intentional single copy — repository documentation at a neutral location, which neither runtime reads from its own tree. Each page renders identically under both prompt renderers, so a second copy would be a byte duplicate and would additionally give two ownership manifests the same paths to manage. The set is declared once in `content/docs/catalog.py`. |
| `settings.json` | `.claude/settings.json` | none | Intentional — Claude-native project settings (plugin enablement, marketplace, permissions, file suggestion). The Codex counterparts are the generated `.codex/config.toml` plus uncommitted personal `config.local.toml`. |
| `scripts/file_suggest.sh` | `.claude/plugins/lup/scripts/file_suggest.sh` | none | Intentional — wired to Claude's native `fileSuggestion` setting; Codex has no equivalent feature. |
| Codex-only files | none | `.codex/config.toml`, `.agents/plugins/marketplace.json` | Intentional — native Codex requirements with no Claude analogue (Claude's marketplace lives inside `.claude/plugins/`). |

## Parity audit of runtime capability families

| Family | Required evidence |
| --- | --- |
| Launch readiness | Exercise the same native startup path a user runs, including implicit services; `Ready` may describe only checks that completed successfully. |
| Authentication | Ask the runtime that owns and refreshes a credential, and cover every user-visible service whose authentication path differs from the primary model transport. Never infer managed-auth readiness from one locally decoded token. |
| Host bridges | Probe the native API each runtime actually calls for clipboard, browser, terminal, and credential access; a command shim proves only callers of that command. Advertised access must match the probe. |
| Delegated-agent paths | Invoke each declared role through every supported runtime with provider-neutral model tiers and tool capabilities; listing a tool or rendering a declaration does not prove the delegated turn can start. |
| Diagnostics and tests | Equivalent failures identify the failed capability, owning runtime, recovery, and affected credential or bridge without exposing secrets. Unit fixtures cover native adapters, and a live requirement exercises each supported startup path. |

### Outer-sandbox clipboard and login handoff

Both runtimes reach the same bounded clipboard broker. Claude Code's command
clients use the image's `xclip` and `wl-paste` shims directly. Codex's native
X11 client uses a private Xvfb server and a python-xlib selection bridge; its
installed CLI has no configurable clipboard-helper command. The composition
declares that transport, not a provider-name branch in the shared launcher.
Only native-X11 sessions start the display, with GLX and TCP disabled and a
per-session Xauthority cookie. Neither transport mounts a host display socket.
The wrapper waits for server and selection ownership before starting the CLI,
then cleans them up with it. Large native transfers are incremental and bounded;
unsupported types are refused, not truncated or forwarded to the desktop.

Regression tests exercise command and native clients against a synthetic
clipboard, including live changes, text copies, image reads, payload limits,
and private-display authentication. Isolated Codex 0.153.4 TUI probes attached
a synthetic PNG through its actual paste shortcut on the host and in the built
image, without a model request or real credentials; the container probe had no
network. This proves the native clipboard path, independently of authentication.
Host-broker discovery reports
only its own result, and private-display startup is checked inside the session.

Host login handoff fingerprints the selected credential fields. A changed host
login replaces those fields once; an unchanged host login preserves the
container's renewed tokens. Claude's shared credentials file retains unrelated
MCP credentials, and Codex's dedicated auth file is replaced as a unit. A
fingerprint is bookkeeping, not authentication evidence: the owning runtime
must still validate or renew its credential in the session's actual boundary.

A separate Codex 0.153.4 outer-container probe successfully forced managed
login renewal through `account/read(refreshToken=true)`. An ephemeral thread
using that saved login then observed `codex_apps` startup go from `starting`
to `ready`. No model turn or app tool call ran. This checks the implicit
service's own authentication path, not merely the primary account response;
it is evidence for the selected account and runtime, not a promise of future
remote-service availability.

## What portable prose may name

Nothing a runtime spells for itself. A skill that means the guidance file, a
settings location, a plugin directory, a model tier, or the runtime's own
documentation says so through a typed part, and the adapter supplies the word:
`scope="this_tree"` when the sentence instructs the reader to act on their own
tree, `scope="every_tree"` when it describes what the repository holds and both
trees must be named. `reject_native_prose` refuses the rest at compile time, so
this is an invariant rather than a convention.

Two things prose may still name, because they are not platform facts. Tool
grants stay literal: `ToolGrant` (`packages/lup/src/lup/types.py`) deliberately
adopts one tool vocabulary for every runtime, so a skill teaching which grants
to declare names them as the closed type spells them. And the SDK symbols in
the guidance's Type Safety section stay literal too — they are importable names
from the library this template builds on, needed verbatim by a reader on either
runtime.
