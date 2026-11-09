import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

// Mirrors engine/gravityguard_engine/pause_switch.py (same file, same JSON schema).
export const DEFAULT_PAUSE_MINUTES = 120;
export const MAX_PAUSE_MINUTES = 480;

export interface PauseState {
  until: number;
  minutes: number;
  reason: string;
  since: number;
  remaining: number;
}

export function pauseFlagPath(): string {
  const override = process.env.GRAVITYGUARD_PAUSE_FILE;
  return override ? override : path.join(os.homedir(), '.gravityguard', 'pause.json');
}

export function pauseFor(minutes: number = DEFAULT_PAUSE_MINUTES, reason = '', nowSec?: number): Omit<PauseState, 'remaining'> {
  const mins = Math.max(1, Math.min(Math.trunc(Number(minutes)) || DEFAULT_PAUSE_MINUTES, MAX_PAUSE_MINUTES));
  const start = nowSec ?? Date.now() / 1000;
  const state = { until: start + mins * 60, minutes: mins, reason: reason.slice(0, 200), since: start };
  const file = pauseFlagPath();
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(file, JSON.stringify(state), 'utf-8');
  return state;
}

export function resumeNow(): boolean {
  try {
    fs.unlinkSync(pauseFlagPath());
    return true;
  } catch {
    return false;
  }
}

export function pauseStatus(nowSec?: number): PauseState | null {
  try {
    const state = JSON.parse(fs.readFileSync(pauseFlagPath(), 'utf-8'));
    const until = Number(state.until);
    if (!Number.isFinite(until)) return null;
    const left = until - (nowSec ?? Date.now() / 1000);
    if (left <= 0) return null;
    return { ...state, until, remaining: Math.floor(left) };
  } catch {
    return null;
  }
}

export function remainingMinutes(state: Pick<PauseState, 'remaining'>): number {
  return Math.max(1, Math.ceil(state.remaining / 60));
}
