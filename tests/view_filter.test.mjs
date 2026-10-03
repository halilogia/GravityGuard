import test from 'node:test';
import assert from 'node:assert/strict';
import { filterEventsAfterSeq, resolveClearedAfterSeq } from '../dist/view_filter.js';

test('filterEventsAfterSeq returns all events when clearedAfterSeq is null', () => {
  const events = [
    { auditSeq: 1, action: 'edit', status: 'BLOCKED' },
    { auditSeq: 2, action: 'save', status: 'APPROVED' },
    { auditSeq: 3, action: 'edit', status: 'WARNING' }
  ];

  const result = filterEventsAfterSeq(events, null);
  assert.equal(result.length, 3);
  assert.deepEqual(result, events);
});

test('filterEventsAfterSeq filters out events with auditSeq <= clearedAfterSeq', () => {
  const events = [
    { auditSeq: 5, action: 'save', status: 'APPROVED' },
    { auditSeq: 4, action: 'edit', status: 'BLOCKED' },
    { auditSeq: 3, action: 'edit', status: 'WARNING' },
    { auditSeq: 2, action: 'save', status: 'APPROVED' },
    { auditSeq: 1, action: 'edit', status: 'BLOCKED' }
  ];

  // Cleared after seq 3
  const result = filterEventsAfterSeq(events, 3);
  assert.equal(result.length, 2);
  assert.equal(result[0].auditSeq, 5);
  assert.equal(result[1].auditSeq, 4);
});

test('filterEventsAfterSeq hides all events if cleared at or above the highest seq', () => {
  const events = [
    { auditSeq: 10, action: 'edit', status: 'BLOCKED' },
    { auditSeq: 9, action: 'save', status: 'APPROVED' }
  ];

  const result = filterEventsAfterSeq(events, 10);
  assert.equal(result.length, 0);

  const resultHigher = filterEventsAfterSeq(events, 15);
  assert.equal(resultHigher.length, 0);
});

test('filterEventsAfterSeq shows subsequent events arriving after clear cursor', () => {
  const clearedAtSeq = 100;
  const subsequentEvents = [
    { auditSeq: 102, action: 'save', status: 'APPROVED' },
    { auditSeq: 101, action: 'edit', status: 'BLOCKED' },
    { auditSeq: 100, action: 'edit', status: 'BLOCKED' },
    { auditSeq: 99, action: 'edit', status: 'WARNING' }
  ];

  const result = filterEventsAfterSeq(subsequentEvents, clearedAtSeq);
  assert.equal(result.length, 2);
  assert.equal(result[0].auditSeq, 102);
  assert.equal(result[1].auditSeq, 101);
});

test('filterEventsAfterSeq excludes events with missing, non-numeric or invalid auditSeq when cleared', () => {
  const events = [
    { auditSeq: 5, action: 'save', status: 'APPROVED' },
    { action: 'legacy_event', status: 'APPROVED' },
    { auditSeq: 'invalid_str', action: 'malformed', status: 'BLOCKED' },
    { auditSeq: NaN, action: 'corrupt', status: 'BLOCKED' },
    { auditSeq: 2, action: 'old_event', status: 'APPROVED' }
  ];

  const result = filterEventsAfterSeq(events, 3);
  assert.equal(result.length, 1);
  assert.equal(result[0].auditSeq, 5);
});

test('resolveClearedAfterSeq extracts lastAuditSeq when valid number', () => {
  const data = {
    activeGuard: 'GravityGuard',
    lastAuditSeq: 42,
    events: [{ auditSeq: 42 }]
  };
  assert.equal(resolveClearedAfterSeq(data), 42);
});

test('resolveClearedAfterSeq falls back to scanning events when lastAuditSeq is missing', () => {
  const data = {
    activeGuard: 'GravityGuard',
    events: [
      { auditSeq: 15 },
      { auditSeq: 28 },
      { auditSeq: 7 }
    ]
  };
  assert.equal(resolveClearedAfterSeq(data), 28);
});

test('resolveClearedAfterSeq safely handles null, undefined, and empty objects', () => {
  assert.equal(resolveClearedAfterSeq(null), 0);
  assert.equal(resolveClearedAfterSeq(undefined), 0);
  assert.equal(resolveClearedAfterSeq({}), 0);
  assert.equal(resolveClearedAfterSeq({ events: [] }), 0);
  assert.equal(resolveClearedAfterSeq({ lastAuditSeq: 'not-a-number' }), 0);
});
