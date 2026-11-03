// Reads and writes per-rule modes in .gravityguard.json ("rules": { ID: { "mode": "shadow" } }), the key the engine reads.
import * as fs from 'fs';

/** Mirrors engine policy_integrity.MANDATORY_RULES: these can never be put in shadow mode. */
export const MANDATORY_RULES = new Set(['G0_SECRET_LEAK', 'G0_ENV_PROTECTION', 'POLICY_INTEGRITY', 'TOOL_SCHEMA_UNSUPPORTED', 'PROJECTION_UNSUPPORTED']);

export type RuleModeChoice = 'shadow' | 'warn' | 'off' | 'default';
const RULE_ID = /^[A-Z][A-Z0-9_]{1,63}$/;

/** Mode configured for a rule, or null when the engine default applies. */
export function configuredMode(cfg: any, ruleId: string): string | null {
  const entry = cfg?.rules?.[ruleId];
  if (typeof entry === 'string') return entry;
  if (entry && typeof entry === 'object' && typeof entry.mode === 'string') return entry.mode;
  return null;
}

/**
 * Sets one rule's mode in a config file, keeping every other key. 'default' removes the entry.
 * Returns false (and writes nothing) for an invalid id, an unknown mode or a mandatory rule.
 */
export function writeRuleMode(cfgPath: string, ruleId: string, mode: RuleModeChoice): boolean {
  if (!RULE_ID.test(ruleId) || !['shadow', 'warn', 'off', 'default'].includes(mode)) return false;
  if (MANDATORY_RULES.has(ruleId) && mode !== 'default') return false;
  let cfg: any = {};
  if (fs.existsSync(cfgPath)) {
    cfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
    if (!cfg || typeof cfg !== 'object' || Array.isArray(cfg)) return false;
  }
  const rules = cfg.rules && typeof cfg.rules === 'object' ? cfg.rules : (cfg.rules = {});
  if (mode === 'default') delete rules[ruleId];
  else rules[ruleId] = { ...(typeof rules[ruleId] === 'object' ? rules[ruleId] : {}), mode };
  fs.writeFileSync(cfgPath, JSON.stringify(cfg, null, 2) + '\n', 'utf8');
  return true;
}
