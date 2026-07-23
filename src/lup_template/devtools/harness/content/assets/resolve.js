// Generated file — do not edit directly. Rendered from
// src/lup_template/devtools/harness/content/assets/resolve.js by
// `uv run lup-devtools harness generate all`.
export const meta = {
  name: 'resolve',
  description: 'Enter Lup\'s shared persisted Python resolver.',
  phases: [{ title: 'Resolve', detail: 'shared Python resolver core' }],
}

function argsError(got) {
  return new Error(
    `resolve args must be a JSON object like {"run_id": "...", "accept": true}; got: ${got}`,
  )
}

// The workflow runtime delivers args parsed, JSON-encoded, or double-encoded.
function normalizeArgs(raw) {
  let value = raw
  for (let decode = 0; typeof value === 'string' && decode < 2; decode += 1) {
    const text = value.trim()
    if (text === '') return {}
    try {
      value = JSON.parse(text)
    } catch {
      throw argsError(text)
    }
  }
  if (value === undefined || value === null) return {}
  if (typeof value !== 'object' || Array.isArray(value)) {
    throw argsError(JSON.stringify(value))
  }
  return value
}

const input = normalizeArgs(args)
const command = [
  'uv',
  'run',
  'lup-devtools',
  'harness',
  'resolve',
  '--adapter',
  'claude',
]
if (input.run_id) {
  command.push('--run-id', String(input.run_id))
}
if (input.accept === true) {
  command.push('--accept')
} else if (input.accept === false) {
  command.push('--reject')
}

const child = Bun.spawn(command, {
  cwd: process.cwd(),
  stdin: 'inherit',
  stdout: 'inherit',
  stderr: 'inherit',
})
const exitCode = await child.exited
if (exitCode !== 0) {
  throw new Error(`shared resolver exited with status ${exitCode}`)
}
return { exit_code: exitCode }
