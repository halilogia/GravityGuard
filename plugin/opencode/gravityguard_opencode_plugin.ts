/**
 * GravityGuard — OpenCode plugin (global install: ~/.config/opencode/plugins/gravityguard.ts)
 *
 * OpenCode v2 plugin contract: `export default { id, setup }` (identical to `Plugin.define({ id, setup })`,
 * written without the `@opencode/plugin` import so a bare local plugin file needs no npm dependency).
 *
 * Bridges OpenCode tool calls to the GravityGuard engine through the Python adapter in
 * `plugin/opencode/gravityguard_opencode_hook.py`, so OpenCode sessions appear in the GravityGuard live stream
 * (and audit log) as the `OpenCode` agent instead of Antigravity IDE.
 *
 * `ctx.tool.hook("execute.before")` blocks by throwing: OpenCode reports the thrown reason as the tool failure and
 * never runs the call. `session.idle` runs the engine's Stop hook so obligations, T1 test evidence and the final
 * secret scan are evaluated and logged; a `continue` verdict is printed to the server log (OpenCode v2 has no
 * forced-continuation stop gate).
 *
 * Fail-open by design: a missing python, adapter or unreadable answer lets the call proceed with a stderr warning.
 * Env overrides: GRAVITYGUARD_OPENCODE_HOOK, GRAVITYGUARD_ENGINE, GRAVITYGUARD_PYTHON.
 */
import { spawnSync } from "node:child_process"
import { existsSync } from "node:fs"
import { homedir } from "node:os"
import path from "node:path"

const DEFAULT_HOOK = path.join(
  homedir(),
  "Desktop",
  "GitHub",
  "Public",
  "GravityGuard",
  "plugin",
  "opencode",
  "gravityguard_opencode_hook.py",
)

const HOOK = process.env.GRAVITYGUARD_OPENCODE_HOOK ?? DEFAULT_HOOK
const PYTHON = process.env.GRAVITYGUARD_PYTHON ?? "python"
const TIMEOUT_MS = 25_000

type Verdict = { block: boolean; reason: string }

/** Tool calls that can carry a file write, a shell command, or a protected read. Everything else skips the engine
 *  so glob/grep/task calls never pay a python spawn. */
const GUARDED_TOOLS = new Set([
  "write",
  "writefile",
  "create_file",
  "edit",
  "editfile",
  "multiedit",
  "multi_edit",
  "patch",
  "apply_patch",
  "apply_diff",
  "bash",
  "read",
  "readfile",
])

type Registration = { dispose(): Promise<void> }
type ToolBeforeEvent = { tool: string; sessionID: string; input: unknown }
type SessionIdleEvent = { type: string; properties?: { sessionID?: string } | undefined }
type PluginContext = {
  readonly location: { readonly directory: string }
  readonly options: Readonly<Record<string, unknown>>
  readonly tool: {
    hook(name: "execute.before", callback: (event: ToolBeforeEvent) => Promise<void> | void): Promise<Registration>
  }
  readonly event: {
    subscribe(options?: {
      types?: string[]
      signal?: AbortSignal
    }): AsyncIterable<SessionIdleEvent>
  }
}

function warn(message: string): void {
  console.warn(`[GravityGuard] ${message}`)
}

/** Briefing file listed under `instructions` in opencode.jsonc; refreshed at startup and whenever a session goes idle. */
const BRIEFING =
  process.env.GRAVITYGUARD_OPENCODE_BRIEFING ??
  path.join(homedir(), ".gemini", "logs", "gravityguard_briefing_opencode.md")

function refreshBriefing(): void {
  if (!existsSync(HOOK)) return
  const result = spawnSync(PYTHON, ["-X", "utf8", HOOK, "--briefing-file", BRIEFING], {
    encoding: "utf8",
    timeout: TIMEOUT_MS,
    windowsHide: true,
    env: process.env,
  })
  if (result.error) warn(`briefing did not run: ${result.error.message}`)
}

/** Runs the adapter; null means "no verdict" (fail-open). */
function askEngine(payload: Record<string, unknown>, stop: boolean): Verdict | null {
  if (!existsSync(HOOK)) {
    warn(`adapter not found: ${HOOK} (set GRAVITYGUARD_OPENCODE_HOOK)`)
    return null
  }
  const result = spawnSync(PYTHON, ["-X", "utf8", HOOK, ...(stop ? ["--stop"] : [])], {
    input: JSON.stringify(payload),
    encoding: "utf8",
    timeout: TIMEOUT_MS,
    windowsHide: true,
    env: process.env,
  })
  if (result.error) {
    warn(`adapter did not run: ${result.error.message}`)
    return null
  }
  if (result.status !== 0) {
    warn(`adapter exited ${result.status}: ${(result.stderr ?? "").trim().slice(0, 300)}`)
    return null
  }
  const lines = (result.stdout ?? "").trim().split(/\r?\n/)
  const last = lines[lines.length - 1] ?? ""
  try {
    const answer = JSON.parse(last)
    if (answer && typeof answer === "object" && typeof answer.block === "boolean") {
      return { block: answer.block, reason: String(answer.reason ?? "") }
    }
  } catch (error) {
    warn(`adapter answer unreadable: ${(error as Error).message}`)
    return null
  }
  return null
}

export default {
  id: "gravityguard",
  async setup(ctx: PluginContext) {
    refreshBriefing()
    await ctx.tool.hook("execute.before", (event) => {
      if (!GUARDED_TOOLS.has(event.tool.toLowerCase())) return
      const verdict = askEngine(
        { tool: event.tool, args: event.input ?? {}, session_id: event.sessionID, cwd: ctx.location.directory },
        false,
      )
      if (!verdict) return
      if (verdict.block) {
        throw new Error(verdict.reason || "[GravityGuard] blocked by policy")
      }
      if (verdict.reason) warn(verdict.reason)
    })

    const controller = new AbortController()
    void (async () => {
      for await (const event of ctx.event.subscribe({ types: ["session.idle"], signal: controller.signal })) {
        const sessionID = event.properties?.sessionID
        const verdict = askEngine({ session_id: sessionID, cwd: ctx.location.directory }, true)
        if (verdict?.block && verdict.reason) warn(verdict.reason)
        refreshBriefing()
      }
    })().catch((error: unknown) => warn(`idle listener stopped: ${(error as Error).message}`))

    return () => controller.abort()
  },
}
