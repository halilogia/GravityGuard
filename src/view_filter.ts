/**
 * GravityGuard - View Filtering Utilities
 * Provides deterministic, sequence-based filtering for the Live monitor feed.
 *
 * Replaces unreliable string timestamp comparisons with monotonic auditSeq filtering.
 */

export interface SequencedEvent {
  auditSeq?: number;
  [key: string]: any;
}

export interface LiveStateSnapshot {
  lastAuditSeq?: number;
  events?: SequencedEvent[];
  [key: string]: any;
}

/**
 * Resolves the monotonic watermark (auditSeq) from the live state snapshot.
 * Prioritizes `data.lastAuditSeq`, then falls back to the maximum `auditSeq`
 * found within `data.events`, or 0 if neither exists.
 */
export function resolveClearedAfterSeq(data: LiveStateSnapshot | null | undefined): number {
  if (!data || typeof data !== 'object') {
    return 0;
  }
  if (typeof data.lastAuditSeq === 'number' && Number.isFinite(data.lastAuditSeq)) {
    return data.lastAuditSeq;
  }
  if (Array.isArray(data.events) && data.events.length > 0) {
    let max = 0;
    for (const ev of data.events) {
      if (typeof ev?.auditSeq === 'number' && Number.isFinite(ev.auditSeq) && ev.auditSeq > max) {
        max = ev.auditSeq;
      }
    }
    return max;
  }
  return 0;
}

/**
 * Filters events based on the clearedAfterSeq cursor.
 * - When clearedAfterSeq is null (unfiltered/initial): returns all events.
 * - When clearedAfterSeq is a number: returns only events where auditSeq > clearedAfterSeq.
 */
export function filterEventsAfterSeq<T extends SequencedEvent>(
  events: T[],
  clearedAfterSeq: number | null
): T[] {
  if (clearedAfterSeq === null) {
    return events;
  }
  return events.filter(
    (e: any) => typeof e?.auditSeq === 'number' && Number.isFinite(e.auditSeq) && e.auditSeq > clearedAfterSeq
  );
}
