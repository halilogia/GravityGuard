// Single source of truth for the rule ids the engine can emit, as the Rules tab shows them.
// Each default effect is what engine/gravityguard_engine/dispatcher.py does when the rule fires:
// block = the operation is denied (or the session cannot stop), warn = allowed with a warning,
// shadow = recorded only, note = bookkeeping that is not a rule (never listed).
// tests/rule_catalog.test.mjs scans the engine sources and fails when an emitted id is missing here.
import { t } from './i18n';
import { MANDATORY_RULES, configuredMode } from './rule_modes';

export type RuleGroup = 'security' | 'architecture' | 'quality' | 'evidence' | 'tooling';
export type RuleEffect = 'block' | 'warn' | 'shadow' | 'note';
export type EffectiveMode = 'block' | 'warn' | 'shadow' | 'off';
/** When the engine evaluates the rule. */
export type RuleStage = 'write' | 'tool' | 'stop' | 'any';
/**
 * How the rule's mode can be changed in .gravityguard.json:
 * shadow = the engine honours "mode": "shadow" (is_rule_shadow); select = shadow/warn/off (OE_SINGLE_IMPL);
 * none = the engine never reads a mode for it.
 */
export type RuleControl = 'shadow' | 'select' | 'none';

export interface RuleInfo {
  id: string;
  group: RuleGroup;
  defaultEffect: RuleEffect;
  stage: RuleStage;
  control: RuleControl;
  mandatory: boolean;
  titleKey: string;
  descKey: string;
  /** Config switch that turns the whole rule off (opt-in / opt-out features); returns false when it is off. */
  enabledBy?: (cfg: any) => boolean;
}

export const RULE_GROUPS: RuleGroup[] = ['security', 'architecture', 'quality', 'evidence', 'tooling'];

const testEvidenceOn = (cfg: any) => cfg?.testEvidence?.enabled !== false;
const dynamicTestsOn = (cfg: any) => testEvidenceOn(cfg) && cfg?.testEvidence?.dynamicExecution === true;
const docObligationsOn = (cfg: any) => cfg?.governance?.enforceDocObligations !== false;
const deliveryGateOn = (cfg: any) => cfg?.deliveryGate?.enabled !== false;

type Row = [id: string, group: RuleGroup, effect: RuleEffect, stage: RuleStage, control: RuleControl, enabledBy?: (cfg: any) => boolean];

const ROWS: Row[] = [
  // Security
  ['G0_SECRET_LEAK', 'security', 'block', 'write', 'none'],
  ['G0_ENV_PROTECTION', 'security', 'block', 'tool', 'none'],
  ['G2_SECURITY_TAMPERING', 'security', 'block', 'write', 'shadow'],
  ['SHELL_SECURITY', 'security', 'block', 'tool', 'none'],
  ['POLICY_INTEGRITY', 'security', 'block', 'write', 'none'],
  ['FINAL_SECURITY_SCAN', 'security', 'block', 'stop', 'none'],
  ['SEC_UNSAFE_PATTERN', 'security', 'warn', 'write', 'shadow'],
  // Architecture
  ['G4_IMPORT_MATRIX', 'architecture', 'block', 'write', 'shadow'],
  ['ARCH_PMA_HORIZONTAL_DENY', 'architecture', 'block', 'write', 'shadow'],
  ['ARCH_PMA_DEEP_IMPORT', 'architecture', 'block', 'write', 'shadow'],
  ['ARCH_PMA_CORE_PURITY', 'architecture', 'block', 'write', 'shadow'],
  ['ARCH_PMA_SHARED_PURITY', 'architecture', 'block', 'write', 'shadow'],
  ['SRP_BOUNDARY', 'architecture', 'block', 'write', 'shadow'],
  ['WEB_INLINE_JS_BUDGET', 'architecture', 'block', 'write', 'shadow'],
  ['WEB_INLINE_CSS_BUDGET', 'architecture', 'block', 'write', 'shadow'],
  ['WEB_MIXED_RESPONSIBILITIES', 'architecture', 'block', 'write', 'shadow'],
  ['WEB_DOCUMENT_SIZE', 'architecture', 'block', 'write', 'shadow'],
  ['ARCH_FILE_GROWTH', 'architecture', 'warn', 'write', 'shadow'],
  ['OE_SPIKE', 'architecture', 'warn', 'write', 'shadow'],
  ['OE_SINGLE_IMPL', 'architecture', 'shadow', 'write', 'select'],
  // Code quality
  ['G1_SILENT_EXCEPTION', 'quality', 'block', 'write', 'shadow'],
  ['G7_TS_FIRST', 'quality', 'block', 'write', 'shadow'],
  ['DESIGN_ICON_RULE', 'quality', 'block', 'write', 'none'],
  ['G3_COMPILER_BYPASS', 'quality', 'warn', 'write', 'shadow'],
  ['STATIC_LINTER_DIAGNOSTIC', 'quality', 'warn', 'write', 'none'],
  ['DESIGN_SCROLLBAR_RULE', 'quality', 'warn', 'write', 'none'],
  // Tests and documentation
  ['G2_TEST_INTEGRITY', 'evidence', 'block', 'write', 'shadow'],
  ['T1_MISSING_RELATED_TEST', 'evidence', 'warn', 'write', 'none', testEvidenceOn],
  ['T2_NO_OBSERVABLE_ASSERTION', 'evidence', 'warn', 'write', 'none', testEvidenceOn],
  ['T3_SYMBOL_TO_TEST_LINK', 'evidence', 'warn', 'write', 'none', testEvidenceOn],
  ['T1_FINAL_UNRESOLVED', 'evidence', 'warn', 'stop', 'none', testEvidenceOn],
  ['T0_TEST_RUN_FAILED', 'evidence', 'warn', 'stop', 'none', dynamicTestsOn],
  ['T0_NO_TESTS_EXECUTED', 'evidence', 'warn', 'stop', 'none', dynamicTestsOn],
  ['T0_COVERAGE_BELOW_THRESHOLD', 'evidence', 'warn', 'stop', 'none', dynamicTestsOn],
  ['TEST_DELETED_SUBJECT_REMAINS', 'evidence', 'warn', 'stop', 'none'],
  ['DOC_OBLIGATION_UNRESOLVED', 'evidence', 'warn', 'stop', 'none', docObligationsOn],
  ['EBDG_UI_SCREENSHOT_PENDING', 'evidence', 'warn', 'stop', 'none', deliveryGateOn],
  // Tool use and the engine itself
  ['TOOL_OUTPUT_BLOAT', 'tooling', 'block', 'tool', 'none'],
  ['G4_NO_BLIND_OVERWRITE', 'tooling', 'block', 'write', 'shadow'],
  ['TOOL_SCHEMA_UNSUPPORTED', 'tooling', 'block', 'tool', 'none'],
  ['PROJECTION_UNSUPPORTED', 'tooling', 'block', 'write', 'none'],
  ['ENGINE_SELF_INTEGRITY', 'tooling', 'block', 'write', 'none'],
  ['STATE_LOCK_TIMEOUT', 'tooling', 'block', 'any', 'none'],
  ['GUARD_UNAVAILABLE', 'tooling', 'block', 'any', 'none'],
];

/** Ids the engine logs for bookkeeping, automation and recovery: recorded in the journal, never listed as rules. */
export const NOTE_RULE_IDS: string[] = [
  'PASS', 'READ_ALLOW', 'EXEMPT', 'T1_PENDING', 'DOC_OBLIGATION_PENDING', 'G7_TS_MANDATORY_FEEDBACK',
  'TASK_ARCHIVE_AUTO', 'TASK_ARCHIVE_ERROR', 'ARCHITECTURE_SYNC_AUTO', 'ARCHITECTURE_SYNC_ERROR',
  'CHANGELOG_AUTO_INJECT', 'KNOWLEDGE_AUTO_INJECT', 'CHANGELOG_AUTO_INJECT_ERROR',
  'STOP_CIRCUIT_BREAKER', 'REMOVAL_OBSERVER_ERROR', 'DELETE_OBSERVED',
  'HOOK_PROPOSAL_APPROVED', 'HOOK_PROPOSAL_REJECTED', 'HOOK_PROPOSAL_REVERTED',
  'USER_ADVISORY_WAIVER', 'GUARD_FALLBACK_LKG', 'GUARD_REPAIR_MODE',
];

function makeInfo(id: string, group: RuleGroup, defaultEffect: RuleEffect, stage: RuleStage, control: RuleControl, enabledBy?: (cfg: any) => boolean): RuleInfo {
  const mandatory = MANDATORY_RULES.has(id);
  return {
    id, group, defaultEffect, stage,
    control: mandatory ? 'none' : control,
    mandatory,
    titleKey: `rules.catalog.${id}.title`,
    descKey: `rules.catalog.${id}.desc`,
    enabledBy
  };
}

export const RULE_CATALOG: RuleInfo[] = [
  ...ROWS.map(([id, group, effect, stage, control, enabledBy]) => makeInfo(id, group, effect, stage, control, enabledBy)),
  ...NOTE_RULE_IDS.map(id => makeInfo(id, 'tooling', 'note', 'any', 'none')),
];

const BY_ID = new Map(RULE_CATALOG.map(r => [r.id, r]));

export function getRule(id: string): RuleInfo | undefined {
  return BY_ID.get(id);
}

/** Rules shown in the tab (bookkeeping notes excluded), in catalog order. */
export function listedRules(): RuleInfo[] {
  return RULE_CATALOG.filter(r => r.defaultEffect !== 'note');
}

function translated(key: string): string | null {
  const v = t(key);
  return v === key ? null : v;
}

/** Localised rule title; the raw id when the rule is not in the catalog or has no translation. */
export function ruleTitle(id: string): string {
  const r = BY_ID.get(id);
  return (r && translated(r.titleKey)) || id;
}

export function ruleDescription(id: string): string {
  const r = BY_ID.get(id);
  return (r && translated(r.descKey)) || '';
}

/**
 * What the engine does with this rule under the given project config: the catalog default, unless the config sets a
 * mode the engine actually reads for it (or switches the feature behind it off).
 */
export function effectiveMode(rule: RuleInfo, cfg: any): EffectiveMode {
  const base: EffectiveMode = rule.defaultEffect === 'note' ? 'off' : rule.defaultEffect;
  if (rule.enabledBy && !rule.enabledBy(cfg)) return 'off';
  if (rule.mandatory) return base;
  const configured = configuredMode(cfg, rule.id);
  if (rule.control === 'shadow' && configured === 'shadow') return 'shadow';
  if (rule.control === 'select' && (configured === 'warn' || configured === 'off' || configured === 'shadow')) return configured;
  return base;
}
