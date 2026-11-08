import * as fs from 'fs';
import * as path from 'path';
import { NON_VIOLATION_RULES } from './audit_stats';

/**
 * Two-stage verification gate shown on the Live tab: GravityGuard shield and logic tests, both derived from the
 * event log (compiler diagnostics count as shield warnings). A test result recorded with `gravityguard gate run tests`
 * is optional and goes back to pending when a file was written after it.
 */

export type GateStatus = 'pass' | 'fail' | 'warn' | 'pending';
export type GateStageId = 'shield' | 'tests';

export interface GateReportEntry {
  status?: string;
  detail?: string;
  command?: string;
  at?: string;
}

export type GateReport = Partial<Record<GateStageId, GateReportEntry>>;

export interface GateEvent {
  status?: string;
  timestamp?: string;
  target?: string;
  ruleId?: string;
  outcome?: string;
}

export interface GateStage {
  id: GateStageId;
  status: GateStatus;
  detail?: string;
  at?: string;
  stale?: boolean;
}

export const GATE_STAGE_ORDER: GateStageId[] = ['shield', 'tests'];

const TEST_FAIL_RULES = new Set(['T0_TEST_RUN_FAILED']);
const TEST_WARN_RULES = new Set(['T0_NO_TESTS_EXECUTED', 'T0_COVERAGE_BELOW_THRESHOLD']);
/** Records that do not change a file, so they neither age a recorded pass nor count for the shield. */
const NON_WRITE_RULES = new Set(['READ_ALLOW', 'BRIEFING_SENT']);

function toMs(stamp: string | undefined): number {
  if (!stamp) {
    return NaN;
  }
  return Date.parse(stamp.includes('T') ? stamp : stamp.replace(' ', 'T'));
}

function isGateStatus(value: unknown): value is GateStatus {
  return value === 'pass' || value === 'fail' || value === 'warn' || value === 'pending';
}

/** Latest event per target, events given newest first. */
function latestPerTarget(events: GateEvent[], keep: (e: GateEvent) => boolean): GateEvent[] {
  const seen = new Map<string, GateEvent>();
  for (const e of events) {
    const key = e.target || '';
    if (!seen.has(key) && keep(e)) {
      seen.set(key, e);
    }
  }
  return [...seen.values()];
}

function fromReport(entry: GateReportEntry | undefined, id: GateStageId, lastWriteMs: number): GateStage | undefined {
  if (!entry || !isGateStatus(entry.status)) {
    return undefined;
  }
  const stage: GateStage = { id, status: entry.status, detail: entry.detail, at: entry.at };
  if (entry.status === 'pass' && toMs(entry.at) < lastWriteMs) {
    return { ...stage, status: 'pending', stale: true };
  }
  return stage;
}

/** An event-derived failure replaces the report entry when it is newer than the report. */
function newer(report: GateStage | undefined, signal: GateStage | undefined): GateStage | undefined {
  if (!signal) {
    return report;
  }
  if (!report || !(toMs(report.at) >= toMs(signal.at))) {
    return signal;
  }
  return report;
}

function testSignal(events: GateEvent[]): GateStage | undefined {
  const last = events.find(e => TEST_FAIL_RULES.has(e.ruleId || '') || TEST_WARN_RULES.has(e.ruleId || ''));
  if (!last) {
    return undefined;
  }
  return { id: 'tests', status: TEST_FAIL_RULES.has(last.ruleId || '') ? 'fail' : 'warn', detail: last.ruleId, at: last.timestamp };
}

function shieldStage(events: GateEvent[]): GateStage {
  const isGuardEvent = (e: GateEvent) => {
    const rule = e.ruleId || '';
    return !TEST_FAIL_RULES.has(rule) && !TEST_WARN_RULES.has(rule) && !NON_WRITE_RULES.has(rule);
  };
  const latest = latestPerTarget(events, isGuardEvent);
  if (latest.length === 0) {
    return { id: 'shield', status: 'pending' };
  }
  const blocked = latest.filter(e => e.status === 'BLOCKED' && e.outcome !== 'RECOVERED');
  if (blocked.length > 0) {
    return { id: 'shield', status: 'fail', detail: blocked[0].ruleId, at: blocked[0].timestamp };
  }
  const warned = latest.filter(e => e.status === 'WARNING' && !NON_VIOLATION_RULES.has(e.ruleId || ''));
  if (warned.length > 0) {
    return { id: 'shield', status: 'warn', detail: warned[0].ruleId, at: warned[0].timestamp };
  }
  return { id: 'shield', status: 'pass', at: latest[0].timestamp };
}

/** Builds the two stages from newest-first events and the optional gate report. */
export function computeVerificationGate(events: GateEvent[], report: GateReport = {}): GateStage[] {
  const lastWriteMs = events.reduce((max, e) => {
    const ms = toMs(e.timestamp);
    return e.target && !NON_WRITE_RULES.has(e.ruleId || '') && Number.isFinite(ms) && ms > max ? ms : max;
  }, -Infinity);
  const tests = newer(fromReport(report.tests, 'tests', lastWriteMs), testSignal(events));
  return [shieldStage(events), tests || { id: 'tests', status: 'pending' }];
}

/** Worst status wins: fail > warn > pending > pass. */
export function overallGateStatus(stages: GateStage[]): GateStatus {
  for (const status of ['fail', 'warn', 'pending'] as GateStatus[]) {
    if (stages.some(s => s.status === status)) {
      return status;
    }
  }
  return 'pass';
}

function readJson<T>(file: string): T | undefined {
  try {
    return fs.existsSync(file) ? JSON.parse(fs.readFileSync(file, 'utf8')) as T : undefined;
  } catch (e) {
    console.warn(`[GravityGuard] Failed to parse ${file}:`, e);
    return undefined;
  }
}

/** Events of this project only: the central live log mixes every project; target-less records are kept. */
export function eventsForProject(events: GateEvent[], workspaceRoot: string): GateEvent[] {
  if (!workspaceRoot) {
    return events;
  }
  const root = path.resolve(workspaceRoot).toLowerCase() + path.sep;
  return events.filter(e => !e.target || (path.resolve(e.target).toLowerCase() + path.sep).startsWith(root));
}

/** Reads verification.json and delivery_receipt.json from the project's runtime folder. */
export function loadVerificationGate(workspaceRoot: string, allEvents: GateEvent[]): GateStage[] {
  const events = eventsForProject(allEvents, workspaceRoot);
  const runtime = workspaceRoot ? path.join(workspaceRoot, '.gravityguard', 'runtime') : '';
  const report = runtime ? readJson<GateReport>(path.join(runtime, 'verification.json')) : undefined;
  return computeVerificationGate(events, report || {});
}
