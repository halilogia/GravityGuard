// Aggregates the permanent audit journal into the numbers the Insights and Rules tabs show.
// Pure module (no vscode import) so it can be unit-tested against fixture journals.
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

export type WindowKey = '24h' | '7d' | '30d' | 'all';
export const WINDOW_KEYS: WindowKey[] = ['24h', '7d', '30d', 'all'];
const WINDOW_MS: Record<WindowKey, number> = { '24h': 864e5, '7d': 7 * 864e5, '30d': 30 * 864e5, all: Infinity };

/** Approved records that are not the write itself; they never fix a violation (mirrors audit.NON_RECOVERING_RULES). */
export const NON_RECOVERING_RULES = new Set(['READ_ALLOW', 'T1_PENDING', 'DOC_OBLIGATION_PENDING', 'G7_TS_MANDATORY_FEEDBACK', 'BRIEFING_SENT']);

/** Rule ids that record compliance or bookkeeping, not a violation. */
export const NON_VIOLATION_RULES = new Set(['PASS', 'EXEMPT', 'READ_ALLOW', 'G7_TS_MANDATORY_FEEDBACK', 'T1_PENDING', 'DOC_OBLIGATION_PENDING', 'BRIEFING_SENT']);

export interface AuditRecord {
  eventId?: string;
  timestamp?: string;
  status?: string;
  outcome?: string;
  ruleId?: string;
  resolvedRuleId?: string;
  target?: string;
  agent?: string;
  conversationId?: string;
  reason?: string;
  recoveryAttempts?: number;
  evasionSuspect?: boolean;
  evasionMarkers?: string[];
}

export interface RuleStat {
  blocked: number;      // first rejections (repeats excluded)
  repeated: number;     // the agent hit the same rule again on the same file
  warned: number;
  shadow: number;       // observed only, nothing was enforced
  recovered: number;    // an approved write cleared the open violation
  evasion: number;      // recoveries whose added lines silence a checker
  falseAlarms: number;  // events the user marked as a false alarm
  lastTs?: string;
  agents: Record<string, number>; // blocked + warned per agent
}

export interface AgentStat {
  agent: string;
  operations: number;   // every audited write/command
  conversations: number;
  blocked: number;
  warned: number;
  recovered: number;
  cleanFirstTry: number; // approved without a preceding violation (outcome CLEAN)
}

export interface DayBucket { day: string; operations: number; blocked: number; warned: number; recovered: number; }

export interface SessionStat {
  id: string;
  agent: string;
  firstTs: string;
  lastTs: string;
  operations: number;
  blocked: number;
  warned: number;
}

export interface AuditEventLite {
  eventId: string;
  timestamp: string;
  status: string;
  ruleId: string;
  target: string;
  agent: string;
  conversationId: string;
  reason: string;
  evasionSuspect: boolean;
  falseAlarm: boolean;
}

export interface WindowStats {
  operations: number;
  blocked: number;
  warned: number;
  recovered: number;
  evasion: number;
  falseAlarms: number;
  rules: Record<string, RuleStat>;
  agents: Record<string, AgentStat>;
  briefing: BriefingStat;
}

export interface BriefingCohort { sessions: number; writes: number; clean: number; }

/** First-try clean writes in sessions that got the session briefing versus those that did not.
 *  Only agents with at least one briefed session count, so agents the briefing never reaches do not skew it. */
export interface BriefingStat { briefed: BriefingCohort; unbriefed: BriefingCohort; }

export interface AuditStats {
  available: boolean;
  totalRecords: number;
  firstTs?: string;
  lastTs?: string;
  windows: Record<WindowKey, WindowStats>;
  daily: DayBucket[];                        // oldest first, last `days` calendar days
  sessions: SessionStat[];                   // most recent first
  recentByRule: Record<string, AuditEventLite[]>; // newest first, violations and recoveries only
}

/** The rule a record is about: a recovery is about the rule it cleared. */
export function recordRule(r: AuditRecord): string {
  if (r.outcome === 'RECOVERED' && r.resolvedRuleId) return r.resolvedRuleId;
  return r.ruleId || 'UNKNOWN';
}

function emptyWindow(): WindowStats {
  return {
    operations: 0, blocked: 0, warned: 0, recovered: 0, evasion: 0, falseAlarms: 0, rules: {}, agents: {},
    briefing: { briefed: { sessions: 0, writes: 0, clean: 0 }, unbriefed: { sessions: 0, writes: 0, clean: 0 } }
  };
}

function ruleOf(w: WindowStats, id: string): RuleStat {
  return w.rules[id] || (w.rules[id] = { blocked: 0, repeated: 0, warned: 0, shadow: 0, recovered: 0, evasion: 0, falseAlarms: 0, agents: {} });
}

function localDay(ms: number): string {
  const d = new Date(ms);
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`;
}

export interface ComputeOptions { now?: number; days?: number; sessionLimit?: number; recentPerRule?: number; }

export function computeAuditStats(records: AuditRecord[], falseAlarmIds: Set<string>, opts: ComputeOptions = {}): AuditStats {
  const now = opts.now ?? Date.now();
  const days = opts.days ?? 14;
  const windows = Object.fromEntries(WINDOW_KEYS.map(k => [k, emptyWindow()])) as Record<WindowKey, WindowStats>;
  const convSets: Record<WindowKey, Record<string, Set<string>>> = { '24h': {}, '7d': {}, '30d': {}, all: {} };
  const convWrites: Record<WindowKey, Map<string, { agent: string; writes: number; clean: number }>> =
    { '24h': new Map(), '7d': new Map(), '30d': new Map(), all: new Map() };
  const briefedConvs = new Set<string>();

  const dayKeys: string[] = [];
  for (let i = days - 1; i >= 0; i--) dayKeys.push(localDay(now - i * 864e5));
  const daily = new Map<string, DayBucket>(dayKeys.map(d => [d, { day: d, operations: 0, blocked: 0, warned: 0, recovered: 0 }]));

  const sessions = new Map<string, SessionStat>();
  const recentByRule: Record<string, AuditEventLite[]> = {};
  let firstTs: string | undefined;
  let lastTs: string | undefined;
  let total = 0;

  for (const r of records) {
    // Maintenance snapshots are journal bookkeeping, not agent activity.
    if (!r || !r.status || !r.timestamp || r.status === 'MAINTENANCE' || (r as any).recordType) continue;
    const ms = Date.parse(r.timestamp);
    if (Number.isNaN(ms)) continue;
    total++;
    if (!firstTs || r.timestamp < firstTs) firstTs = r.timestamp;
    if (!lastTs || r.timestamp > lastTs) lastTs = r.timestamp;

    const rule = recordRule(r);
    const agent = r.agent || 'Unknown';
    const conv = r.conversationId || 'default';
    const nonViolation = NON_VIOLATION_RULES.has(r.ruleId || '');
    const isBlocked = r.status === 'BLOCKED' && r.outcome !== 'REPEATED_VIOLATION';
    const isRepeat = r.outcome === 'REPEATED_VIOLATION';
    const isWarn = r.status === 'WARNING' && !nonViolation;
    const isShadow = r.status === 'SHADOW_TRIGGER';
    // Older journals let a read or a bookkeeping note clear a violation; that was never a fix.
    const isRecovered = r.outcome === 'RECOVERED' && !NON_RECOVERING_RULES.has(r.ruleId || '');
    // An operation is one write or command attempt: an approved write or a rejection. Reads, warnings
    // (the write still passes) and bookkeeping lines are not separate attempts.
    const isOperation = r.ruleId === 'PASS' || r.status === 'BLOCKED';
    const isFalseAlarm = !!r.eventId && falseAlarmIds.has(r.eventId);
    if (r.ruleId === 'BRIEFING_SENT') briefedConvs.add(conv);

    for (const key of WINDOW_KEYS) {
      if (now - ms > WINDOW_MS[key]) continue;
      const w = windows[key];
      const a = w.agents[agent] || (w.agents[agent] = { agent, operations: 0, conversations: 0, blocked: 0, warned: 0, recovered: 0, cleanFirstTry: 0 });
      const cs = convSets[key][agent] || (convSets[key][agent] = new Set());
      cs.add(conv);
      if (isOperation) {
        w.operations++; a.operations++;
        const cw = convWrites[key].get(conv) || { agent, writes: 0, clean: 0 };
        cw.writes++;
        if (r.outcome === 'CLEAN' && r.ruleId === 'PASS') cw.clean++;
        convWrites[key].set(conv, cw);
      }
      if (r.outcome === 'CLEAN' && r.ruleId === 'PASS') a.cleanFirstTry++;
      if (isBlocked || isRepeat || isWarn || isShadow || isRecovered) {
        const rs = ruleOf(w, rule);
        if (!rs.lastTs || r.timestamp > rs.lastTs) rs.lastTs = r.timestamp;
        if (isBlocked) { rs.blocked++; w.blocked++; a.blocked++; }
        if (isRepeat) rs.repeated++;
        if (isWarn) { rs.warned++; w.warned++; a.warned++; }
        if (isShadow) rs.shadow++;
        if (isRecovered) { rs.recovered++; w.recovered++; a.recovered++; }
        if (isRecovered && r.evasionSuspect) { rs.evasion++; w.evasion++; }
        if (isFalseAlarm) { rs.falseAlarms++; w.falseAlarms++; }
        if (isBlocked || isWarn) rs.agents[agent] = (rs.agents[agent] || 0) + 1;
      }
    }

    const bucket = daily.get(localDay(ms));
    if (bucket) {
      if (isOperation) bucket.operations++;
      if (isBlocked) bucket.blocked++;
      if (isWarn) bucket.warned++;
      if (isRecovered) bucket.recovered++;
    }

    const s = sessions.get(conv) || { id: conv, agent, firstTs: r.timestamp, lastTs: r.timestamp, operations: 0, blocked: 0, warned: 0 };
    if (r.timestamp < s.firstTs) s.firstTs = r.timestamp;
    if (r.timestamp > s.lastTs) { s.lastTs = r.timestamp; s.agent = agent; }
    if (isOperation) s.operations++;
    if (isBlocked) s.blocked++;
    if (isWarn) s.warned++;
    sessions.set(conv, s);

    if (isBlocked || isRepeat || isWarn || isShadow || isRecovered) {
      (recentByRule[rule] || (recentByRule[rule] = [])).push({
        eventId: r.eventId || '',
        timestamp: r.timestamp,
        status: isRecovered ? 'RECOVERED' : r.status,
        ruleId: rule,
        target: r.target || '',
        agent,
        conversationId: conv,
        reason: (r.reason || '').slice(0, 240),
        evasionSuspect: !!r.evasionSuspect,
        falseAlarm: isFalseAlarm
      });
    }
  }

  for (const key of WINDOW_KEYS) {
    for (const [agent, set] of Object.entries(convSets[key])) windows[key].agents[agent].conversations = set.size;
    const reached = new Set([...convWrites[key]].filter(([c]) => briefedConvs.has(c)).map(([, v]) => v.agent));
    for (const [c, v] of convWrites[key]) {
      if (!reached.has(v.agent)) continue;
      const cohort = briefedConvs.has(c) ? windows[key].briefing.briefed : windows[key].briefing.unbriefed;
      cohort.sessions++; cohort.writes += v.writes; cohort.clean += v.clean;
    }
  }
  const perRule = opts.recentPerRule ?? 10;
  for (const id of Object.keys(recentByRule)) {
    recentByRule[id] = recentByRule[id].sort((x, y) => (x.timestamp < y.timestamp ? 1 : -1)).slice(0, perRule);
  }

  return {
    available: total > 0,
    totalRecords: total,
    firstTs,
    lastTs,
    windows,
    daily: dayKeys.map(d => daily.get(d)!),
    sessions: [...sessions.values()].sort((x, y) => (x.lastTs < y.lastTs ? 1 : -1)).slice(0, opts.sessionLimit ?? 30),
    recentByRule
  };
}

export function auditLogDir(): string {
  return path.join(os.homedir(), '.gemini', 'logs');
}
export const AUDIT_FILE = 'gravityguard_permanent_audit.jsonl';
export const FALSE_ALARM_FILE = 'gravityguard_false_alarms.jsonl';

const MAX_READ_BYTES = 32 * 1024 * 1024;

function readJsonl<T>(file: string): T[] {
  if (!fs.existsSync(file)) return [];
  const size = fs.statSync(file).size;
  let text: string;
  if (size > MAX_READ_BYTES) {
    // Very large journals: only the newest part; the first partial line is dropped below.
    const fd = fs.openSync(file, 'r');
    try {
      const buf = Buffer.alloc(MAX_READ_BYTES);
      fs.readSync(fd, buf, 0, MAX_READ_BYTES, size - MAX_READ_BYTES);
      text = buf.toString('utf8');
      text = text.slice(text.indexOf('\n') + 1);
    } finally {
      fs.closeSync(fd);
    }
  } else {
    text = fs.readFileSync(file, 'utf8');
  }
  const out: T[] = [];
  for (const line of text.split('\n')) {
    if (!line.trim()) continue;
    try { out.push(JSON.parse(line)); } catch { /* torn line during a concurrent append */ }
  }
  return out;
}

export function readFalseAlarmIds(dir = auditLogDir()): Set<string> {
  const ids = new Set<string>();
  for (const r of readJsonl<{ eventId?: string; undone?: boolean }>(path.join(dir, FALSE_ALARM_FILE))) {
    if (!r.eventId) continue;
    if (r.undone) ids.delete(r.eventId); else ids.add(r.eventId);
  }
  return ids;
}

/** Appends a false-alarm mark (or its undo) for one audit event. */
export function writeFalseAlarm(eventId: string, ruleId: string, undone: boolean, dir = auditLogDir()): void {
  fs.mkdirSync(dir, { recursive: true });
  fs.appendFileSync(path.join(dir, FALSE_ALARM_FILE),
    JSON.stringify({ eventId, ruleId, undone, timestamp: new Date().toISOString() }) + '\n', 'utf8');
}

let cache: { key: string; stats: AuditStats } | null = null;

/** Reads and aggregates the journal; re-reads only when the journal or the false-alarm file changed. */
export function loadAuditStats(dir = auditLogDir()): AuditStats {
  const auditPath = path.join(dir, AUDIT_FILE);
  const faPath = path.join(dir, FALSE_ALARM_FILE);
  const sig = (p: string) => { try { const s = fs.statSync(p); return `${s.size}:${s.mtimeMs}`; } catch { return '-'; } };
  // The day changes the buckets even when no file changed.
  const key = `${dir}|${sig(auditPath)}|${sig(faPath)}|${localDay(Date.now())}`;
  if (cache && cache.key === key) return cache.stats;
  const stats = computeAuditStats(readJsonl<AuditRecord>(auditPath), readFalseAlarmIds(dir));
  cache = { key, stats };
  return stats;
}
