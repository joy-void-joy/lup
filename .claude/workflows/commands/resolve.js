// Generated file — do not edit directly. Rendered from
// lup.adapters.claude.harness by `uv run lup-devtools harness generate all`.
export const meta = {
  name: 'resolve',
  description: 'Enter Lup\'s shared persisted Python resolver.',
  phases: [{ title: 'Resolve', detail: 'shared Python resolver core' }],
}

const input = typeof args === 'string' ? JSON.parse(args) : args || {}
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
  command.push('--run-id', input.run_id)
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
