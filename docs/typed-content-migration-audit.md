# Typed-content migration audit

This is the one-time review record for replacing the encoded native catalog
with typed canonical content. The comparison baseline is `743a948`, immediately
before migration commit `a770c5e`. Byte equality with the retired catalog is
not a maintained contract; every output difference is classified below, while
deterministic regeneration and ownership drift remain permanent gates.

## Classified output changes

| Output family | Reviewed change | Disposition |
|---|---|---|
| Claude commands and Codex skills | Frontmatter is rendered from `Skill`: field ordering and quoting are normalized, empty argument lists are omitted, declared arguments are explicit, and descriptions converge on the canonical declaration. Prompt bodies render semantic `ArgumentsRef` and `SkillInvocation` parts with native spellings. | Accepted renderer output |
| Claude and Codex agents | Descriptions, tools, models, and colors render from `Agent`. Example-heavy Claude selection descriptions that were not represented in the portable model are removed; Codex writes the inherited model explicitly. Agent instruction bodies remain canonical typed prose. | Accepted canonical metadata |
| Repository guidance | `.claude/CLAUDE.md` and `AGENTS.md` render from the same portable guidance with only native invocation spelling differences. The downstream-project scaffold is an independently typed, section-marked `TEMPLATE_CLAUDE.md`, rather than an accidental second repository-guidance source. | Accepted ownership correction |
| Plugin manifests and settings | JSON is rendered deterministically from typed models. Object order and formatting normalize; legacy Claude-only author and keyword metadata, which had no portable declaration, are removed. | Accepted model boundary |
| Plain assets | `file_suggest.sh` is copied from a readable committed asset rather than decoded catalog bytes. | Content preserved under explicit ownership |
| Policy runtime | The copied kernel gains the AST and string-literal context used to keep prose examples out of anti-pattern and marker decisions. Generated data changes only when canonical rule rows or `HookSet` configuration change. | Accepted Workstream K dependency |

## Permanent evidence

- The canonical inventory contains 30 skills and five agents, and both native
  compilers emit all 30 skill artifacts.
- Canonical serialized content contains no Claude or Codex invocation spelling.
- The content package participates in the repository native-spelling audit.
  Documents whose subject matter is a native manifest or hook use an audited,
  typed suppression instead of inheriting a directory-wide exemption.
- `ArgumentsRef` and `SkillInvocation` have explicit renderer fixtures for both
  native targets, and model validation rejects an argument declaration without
  a reference or a reference without declared arguments.
- The content package contains no embedded base64, and the deleted catalog,
  parity reader, description importer, and prompt string scanner have no live
  references.
- Both native trees compile deterministically, carry identical copied kernel
  bytes, and pass the repository ownership-drift check.
- A canonical prose edit changes one declaration and its reviewed generated
  artifacts; native artifact edits remain explicit reconciliation conflicts.

These properties are pinned by `tests/unit/test_harness_compilation.py`, the
semantic-policy fixtures, the generated-tree drift workflow, and the adopter
walkthroughs. Future renderer changes are reviewed directly against typed
source; they do not reopen this historical migration baseline.
