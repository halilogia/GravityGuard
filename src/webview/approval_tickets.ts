import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { runHookControl } from './hook_proposals';

export interface ApprovalView {
  id: string;
  rule: string;
  reason: string;
  seen: number;
  action: { tool: string; target: string; command: string };
}

export const APPROVAL_ID = /^[0-9a-f]{16}$/;

function pendingDir(): string {
  const override = process.env.GRAVITYGUARD_APPROVAL_DIR;
  return path.join(override || path.join(os.homedir(), '.gravityguard', 'approvals'), 'pending');
}

/** Cheap change marker: names, sizes and times of the ticket files. */
export function approvalSignature(): string {
  const folder = pendingDir();
  let names: string[] = [];
  try { names = fs.readdirSync(folder).filter(name => name.endsWith('.json')).sort(); }
  catch { return ''; } // the folder does not exist until a rule blocks something
  return names.map(name => {
    try {
      const stat = fs.statSync(path.join(folder, name));
      return `${name}:${stat.size}:${stat.mtimeMs}`;
    } catch { return `${name}:gone`; }
  }).join('|');
}

/**
 * Keeps the last ticket listing from engine/approval_control.py. Rendering stays synchronous: a changed signature
 * starts one background refresh, and `onChange` receives the tickets that were not in the previous listing.
 */
export class ApprovalCache {
  private data: ApprovalView[] = [];
  private signature = '';
  private running = false;
  private known = new Set<string>();

  constructor(private readonly script: string, private readonly onChange: (fresh: ApprovalView[]) => void) {}

  current(): ApprovalView[] {
    const signature = approvalSignature();
    if (signature !== this.signature && !this.running) {
      this.signature = signature;
      this.running = true;
      let fresh: ApprovalView[] = [];
      runHookControl(this.script, { action: 'list' })
        .then(answer => {
          if (!answer || !Array.isArray(answer.pending)) return;
          this.data = answer.pending.filter((ticket: ApprovalView) => APPROVAL_ID.test(ticket.id));
          fresh = this.data.filter(ticket => !this.known.has(ticket.id));
          this.data.forEach(ticket => this.known.add(ticket.id));
        })
        .catch(error => console.warn('[GravityGuard] Approval listing failed:', error))
        .finally(() => { this.running = false; this.onChange(fresh); });
    }
    return this.data;
  }

  invalidate(): void {
    this.signature = '';
  }
}
