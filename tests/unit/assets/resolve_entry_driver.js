// Execute the Claude resolver workflow entry the way the workflow runtime
// does: the script body becomes an async function body receiving `args`,
// with `Bun` shadowed by a spawn stub that records each launched command.
import { readFileSync } from 'node:fs'

const [entryPath, envelopeText] = process.argv.slice(2)
const envelope = JSON.parse(envelopeText)
const source = readFileSync(entryPath, 'utf8').replace(
  'export const meta',
  'const meta',
)
const AsyncFunction = Object.getPrototypeOf(async function () {}).constructor
const run = new AsyncFunction('args', 'Bun', source)

const spawned = []
const exitCode = envelope.exit ?? 0
const bunStub = {
  spawn(command) {
    spawned.push(command)
    return { exited: Promise.resolve(exitCode) }
  },
}
const delivered = envelope.delivery === 'absent' ? undefined : envelope.value
try {
  const result = await run(delivered, bunStub)
  console.log(JSON.stringify({ ok: true, result, spawned })) // lup: ignore[console-log] — stdout is the driver's protocol
} catch (error) {
  console.log( // lup: ignore[console-log] — stdout is the driver's protocol
    JSON.stringify({ ok: false, message: String(error.message ?? error), spawned }),
  )
}
