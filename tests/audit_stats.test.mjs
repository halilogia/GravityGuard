import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { computeAuditStats, loadAuditStats, writeFalseAlarm, readFalseAlarmIds } from '../dist/audit_stats.js';
import { writeRuleMode, configuredMode } from '../dist/rule_modes.js';

const NOW = Date.parse('2026-11-03T12:00:00Z');
const at = h => new Date(NOW - h * 3600e3).toISOString();
const rec = (h, status, outcome, ruleId, extra = {}) => ({ eventId: `e${h}${status}${ruleId}`, timestamp: at(h), status, outcome, ruleId, agent: 'OpenCode', conversationId: 'c1', target: 'a.ts', ...extra });

test('windows split by age; repeats and compliance notes are not counted as violations', () => {
  const s = computeAuditStats([
    rec(1, 'BLOCKED', 'BLOCKED', 'G1_SILENT_EXCEPTION'),
    rec(1.5, 'BLOCKED', 'REPEATED_VIOLATION', 'G1_SILENT_EXCEPTION'),
    rec(2, 'APPROVED', 'RECOVERED', 'PASS', { resolvedRuleId: 'G1_SILENT_EXCEPTION', evasionSuspect: true }),
    rec(48, 'WARNING', 'WARNING', 'G7_TS_MANDATORY_FEEDBACK'),
    rec(72, 'WARNING', 'WARNING', 'ARCH_FILE_GROWTH', { agent: 'Claude Code', conversationId: 'c2' }),
    rec(80, 'APPROVED', 'CLEAN', 'PASS', { agent: 'Claude Code', conversationId: 'c2' }),
    rec(81, 'APPROVED', 'CLEAN', 'T1_PENDING', { agent: 'Claude Code', conversationId: 'c2' }),
    { timestamp: at(1), status: 'MAINTENANCE', recordType: 'snapshot' }
  ], new Set(), { now: NOW });
  const d = s.windows['24h'];
  assert.equal(d.blocked, 1);
  assert.equal(d.rules.G1_SILENT_EXCEPTION.repeated, 1);
  assert.equal(d.rules.G1_SILENT_EXCEPTION.recovered, 1);
  assert.equal(d.rules.G1_SILENT_EXCEPTION.evasion, 1);
  assert.equal(s.windows['7d'].warned, 1, 'G7 feedback is compliance, not a warning');
  assert.equal(s.windows['7d'].agents['Claude Code'].cleanFirstTry, 1, 'bookkeeping approvals are not clean operations');
  assert.ok(!s.windows.all.agents.Unknown, 'maintenance snapshots are skipped');
  assert.equal(s.windows['7d'].agents['Claude Code'].conversations, 1);
  assert.equal(s.daily.length, 14);
  assert.equal(s.sessions[0].id, 'c1', 'most recent session first');
  assert.equal(s.recentByRule.G1_SILENT_EXCEPTION[0].status, 'BLOCKED');
});

test('false alarm marks count per rule and can be undone', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-fa-'));
  writeFalseAlarm('e1', 'G1_SILENT_EXCEPTION', false, dir);
  writeFalseAlarm('e2', 'G1_SILENT_EXCEPTION', false, dir);
  writeFalseAlarm('e2', 'G1_SILENT_EXCEPTION', true, dir);
  assert.deepEqual([...readFalseAlarmIds(dir)], ['e1']);
  fs.writeFileSync(path.join(dir, 'gravityguard_permanent_audit.jsonl'),
    JSON.stringify({ eventId: 'e1', timestamp: new Date().toISOString(), status: 'BLOCKED', outcome: 'BLOCKED', ruleId: 'G1_SILENT_EXCEPTION', agent: 'Codex' }) + '\n{torn');
  const s = loadAuditStats(dir);
  assert.equal(s.windows.all.rules.G1_SILENT_EXCEPTION.falseAlarms, 1);
  assert.ok(s.recentByRule.G1_SILENT_EXCEPTION[0].falseAlarm);
});

test('rule modes are written under "rules", mandatory rules cannot be shadowed', () => {
  const dir = fs.mkdtempSync(path.join(os.tmpdir(), 'gg-rm-'));
  const cfg = path.join(dir, '.gravityguard.json');
  fs.writeFileSync(cfg, JSON.stringify({ complexity: { totalLoc: 500 } }));
  assert.ok(writeRuleMode(cfg, 'G1_SILENT_EXCEPTION', 'shadow'));
  let data = JSON.parse(fs.readFileSync(cfg, 'utf8'));
  assert.equal(configuredMode(data, 'G1_SILENT_EXCEPTION'), 'shadow');
  assert.equal(data.complexity.totalLoc, 500, 'other keys kept');
  assert.equal(writeRuleMode(cfg, 'G0_SECRET_LEAK', 'shadow'), false);
  assert.equal(writeRuleMode(cfg, 'bad id', 'shadow'), false);
  assert.ok(writeRuleMode(cfg, 'G1_SILENT_EXCEPTION', 'default'));
  data = JSON.parse(fs.readFileSync(cfg, 'utf8'));
  assert.equal(configuredMode(data, 'G1_SILENT_EXCEPTION'), null);
});

test('briefing cohorts compare first-try clean writes, only for agents the briefing reaches', () => {
  const ag = (h, status, outcome, ruleId, conv, agent = 'Antigravity IDE') => rec(h, status, outcome, ruleId, { agent, conversationId: conv });
  const s = computeAuditStats([
    ag(1, 'APPROVED', 'CLEAN', 'BRIEFING_SENT', 'b1'),
    ag(1, 'APPROVED', 'CLEAN', 'PASS', 'b1'),
    ag(1.1, 'APPROVED', 'CLEAN', 'PASS', 'b1'),
    ag(2, 'BLOCKED', 'BLOCKED', 'G1_SILENT_EXCEPTION', 'u1'),
    ag(2.1, 'APPROVED', 'RECOVERED', 'PASS', 'u1'),
    ag(3, 'APPROVED', 'CLEAN', 'PASS', 'o1', 'OpenCode')
  ], new Set(), { now: NOW });
  const b = s.windows['24h'].briefing;
  assert.deepEqual(b.briefed, { sessions: 1, writes: 2, clean: 2 });
  assert.deepEqual(b.unbriefed, { sessions: 1, writes: 2, clean: 0 }, 'OpenCode is never briefed here, so it is left out');
  assert.equal(s.windows['24h'].operations, 5, 'the briefing mark is not a write');
});
