export const meta = {
  name: 'resolve',
  description: 'Enter Lup\'s shared persisted Python resolver.',
  phases: [{ title: 'Resolve', detail: 'shared Python resolver core' }],
}

// This adapter artifact owns only native argument handling and process launch.
// The Python core owns questions, leases, scheduling, worktrees, review,
// integration, verification, human acceptance, and cleanup.
const input = typeof args === 'string' ? JSON.parse(args) : args || {}
if (!input.run_id) {
  throw new Error('resolve requires run_id')
}

const command = [
  'uv',
  'run',
  'lup-devtools',
  'harness',
  'resolve',
  '--adapter',
  'claude',
  '--run-id',
  input.run_id,
]
if (input.inventory) {
  command.push('--inventory', input.inventory)
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
