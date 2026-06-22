export const meta = {
  name: 'resolve',
  description:
    'Execute phase of /lup:resolve: one isolated-worktree editor per approved concern, each independently verified. Returns a manifest of branches to merge; merges nothing itself.',
  phases: [
    { title: 'Edit', detail: 'one worktree-isolated agent per concern' },
    { title: 'Verify', detail: 'skeptical check of each diff against its original notes' },
  ],
}

// args = {
//   base: string,                     // ref the worktrees branch from / the verifier diffs against
//   concerns: [{
//     id: string,                     // slug; becomes branch resolve/<id>
//     title: string,
//     spec: string,                   // generalized, marker-free task (user decisions baked in)
//     files: string[],                // declared blast radius — starting points, not a fence
//     notes: [{ file, line, text }],  // the original markers this concern subsumes
//   }],
// }
const base = (args && args.base) || 'HEAD'
const concerns = (args && args.concerns) || []

if (!concerns.length) {
  log('No concerns passed; nothing to execute.')
  return { manifest: [] }
}

const EDIT_SCHEMA = {
  type: 'object',
  required: ['branch', 'committed', 'summary', 'files_changed'],
  properties: {
    branch: { type: 'string', description: 'Branch the work was committed to (resolve/<id>)' },
    committed: { type: 'boolean', description: 'Whether a commit was actually made' },
    summary: { type: 'string', description: 'Concern-level summary of what changed and why' },
    files_changed: { type: 'array', items: { type: 'string' } },
    swept_beyond_scope: {
      type: 'array',
      items: { type: 'string' },
      description: 'Files edited outside the declared scope because the pattern lived there too',
    },
  },
}

const VERDICT_SCHEMA = {
  type: 'object',
  required: ['addressed', 'reason'],
  properties: {
    addressed: {
      type: 'boolean',
      description:
        'True ONLY if the diff genuinely fixes the underlying issue across the whole pattern — not one site, not cosmetic, not a marker deletion',
    },
    generalized: {
      type: 'boolean',
      description: 'Whether the fix covered every instance of the pattern, not just the noted line',
    },
    reason: { type: 'string' },
    residual: { type: 'string', description: 'What remains unaddressed, if anything' },
    note_findings: {
      type: 'array',
      description: 'One entry per ORIGINAL review note: whether and how the diff addresses it',
      items: {
        type: 'object',
        required: ['file', 'line', 'addressed', 'how'],
        properties: {
          file: { type: 'string' },
          line: { type: 'integer' },
          addressed: { type: 'boolean' },
          how: {
            type: 'string',
            description: 'The concrete change that resolves this note, or why it is unaddressed',
          },
        },
      },
    },
  },
}

function editPrompt(c) {
  const starts = (c.files || []).join(', ') || '(discover them)'
  const targets = (c.notes || []).map((n) => `${n.file}:${n.line}`).join(' ')
  const strip = targets
    ? `uv run lup-devtools dev comments --clear ${targets}`
    : `true   # this concern has no markers to strip`
  return [
    `Resolve a code-quality concern on a dedicated branch in this repository.`,
    ``,
    `CONCERN (${c.id}): ${c.title}`,
    c.spec,
    ``,
    `Your spec is the description above — fix the UNDERLYING issue, not a single line.`,
    `If it is a pattern (a missing type alias, backend logic leaking into core, a`,
    `duplicated construction, ...), find and fix EVERY instance across the codebase,`,
    `not just the first. Likely starting points: ${starts}.`,
    ``,
    `Steps:`,
    `1. git checkout -b resolve/${c.id}   (branch from ${base})`,
    `2. ${strip}`,
    `   This strips THIS concern's \`# claude:\` markers from your worktree so you`,
    `   fix the issue itself, not the note. Do not re-add markers or leave`,
    `   explanatory comments in their place — reshape the code so it reads alone.`,
    `3. Make the changes.`,
    `4. uv run ruff format . && uv run ruff check . && uv run pyright; run uv run`,
    `   pytest if behavior could change. Fix what you break.`,
    `5. git add -A && git commit -m "fix(resolve): ${c.title}"`,
    ``,
    `Return the branch name, whether you committed, a concern-level summary, the`,
    `files changed, and any files you swept beyond the declared scope.`,
  ].join('\n')
}

function verifyPrompt(c, edit) {
  const notes = (c.notes || []).map((n) => `- ${n.file}:${n.line} ${n.text}`).join('\n')
  return [
    `Independently verify whether a change genuinely resolves a concern.`,
    `Be skeptical; default to addressed=false when unsure.`,
    ``,
    `CONCERN (${c.id}): ${c.title}`,
    c.spec,
    ``,
    `ORIGINAL review notes this concern must satisfy:`,
    notes || '(none recorded)',
    ``,
    `The work is on branch \`${edit.branch}\`. Inspect it:`,
    `  git diff ${base}...${edit.branch}`,
    `Read the changed files at that branch as needed.`,
    ``,
    `The branch also deletes this concern's \`# claude:\` marker lines — that strip`,
    `happens at fork and is expected; it is NOT the fix. Judge the code change.`,
    ``,
    `Judge: does the diff fix what every note points at, across the whole pattern —`,
    `not just the exact noted site? A fix that edits only the noted line, resolves`,
    `nothing, or merely removes a marker is addressed=false. Put anything left in`,
    `'residual'.`,
    ``,
    `Also produce 'note_findings': one entry for EACH original note above — its`,
    `file and line, whether the diff addresses it, and HOW (the concrete change`,
    `that resolves it, or why it remains). This is shown to a human reviewer, so`,
    `make 'how' specific and readable.`,
  ].join('\n')
}

phase('Edit')
const results = await pipeline(
  concerns,
  (c) =>
    agent(editPrompt(c), {
      label: `edit:${c.id}`,
      phase: 'Edit',
      isolation: 'worktree',
      agentType: 'lup:resolve-editor',
      schema: EDIT_SCHEMA,
    }).then((edit) => ({ c, edit })),
  ({ c, edit }) =>
    !edit || !edit.committed
      ? { c, edit, verdict: null }
      : agent(verifyPrompt(c, edit), {
          label: `verify:${c.id}`,
          phase: 'Verify',
          schema: VERDICT_SCHEMA,
        }).then((verdict) => ({ c, edit, verdict })),
)

const manifest = results.filter(Boolean).map((r) => ({
  id: r.c.id,
  title: r.c.title,
  spec: r.c.spec || '',
  branch: r.edit ? r.edit.branch : null,
  committed: !!(r.edit && r.edit.committed),
  accepted: !!(r.verdict && r.verdict.addressed),
  generalized: !!(r.verdict && r.verdict.generalized),
  reason: r.verdict ? r.verdict.reason : 'no edit committed',
  residual: r.verdict ? r.verdict.residual || '' : '',
  summary: r.edit ? r.edit.summary || '' : '',
  files_changed: r.edit ? r.edit.files_changed || [] : [],
  swept_beyond_scope: r.edit ? r.edit.swept_beyond_scope || [] : [],
  note_findings: r.verdict ? r.verdict.note_findings || [] : [],
  notes: r.c.notes || [],
}))

const accepted = manifest.filter((m) => m.accepted).length
log(`${accepted}/${manifest.length} concerns verified as addressed.`)
return { manifest }
