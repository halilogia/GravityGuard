import { spawn } from 'child_process';
import * as fs from 'fs';
import * as path from 'path';

export interface HookProposalView {
  id: string;
  root: string;
  path: string;
  sha256?: string;
  valid: boolean;
  error?: string;
  diff?: string;
  target_file?: string;
  proposal?: Record<string, any>;
}

export interface HookReceiptView {
  id: string;
  root: string;
  status: string;
  target_file: string;
  proposal: Record<string, any>;
}

export interface HookProposalData {
  pending: HookProposalView[];
  installed: HookReceiptView[];
}

export const PROPOSALS_DIR = path.join('.gravityguard', 'proposals', 'hooks');
export const RECEIPTS_DIR = path.join('.gravityguard', 'runtime', 'hook-receipts');

/** Runs the trusted engine command (engine/hook_proposal_control.py): JSON request in, JSON answer out. */
export function runHookControl(script: string, request: Record<string, unknown>): Promise<any> {
  return new Promise((resolve, reject) => {
    const proc = spawn(process.env.GRAVITYGUARD_PYTHON || 'python', ['-X', 'utf8', script], {
      cwd: path.dirname(script), windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']
    });
    let out = '';
    const timer = setTimeout(() => { proc.kill(); reject(new Error('Hook proposal command timed out')); }, 15000);
    proc.stdout.setEncoding('utf8');
    proc.stdout.on('data', chunk => { out += chunk; });
    proc.stderr.resume();
    proc.on('error', error => { clearTimeout(timer); reject(error); });
    proc.on('close', () => {
      clearTimeout(timer);
      try { resolve(JSON.parse(out)); }
      catch { reject(new Error('Hook proposal command returned no answer')); }
    });
    proc.stdin.on('error', () => { /* The missing answer reports the failure. */ });
    proc.stdin.end(JSON.stringify(request));
  });
}

/** Cheap change marker: names, sizes and times of proposal and receipt files under every root. */
export function hookFilesSignature(roots: string[]): string {
  const parts: string[] = [];
  for (const root of roots) {
    for (const dir of [PROPOSALS_DIR, RECEIPTS_DIR]) {
      const folder = path.join(root, dir);
      let names: string[] = [];
      try { names = fs.readdirSync(folder).filter(name => name.endsWith('.json')).sort(); }
      catch { continue; } // the folder does not exist until an agent proposes something
      for (const name of names) {
        try {
          const stat = fs.statSync(path.join(folder, name));
          parts.push(`${folder}/${name}:${stat.size}:${stat.mtimeMs}`);
        } catch { parts.push(`${folder}/${name}:gone`); }
      }
    }
  }
  return parts.join('|');
}

/**
 * Keeps the last engine listing. Rendering stays synchronous: a changed signature starts one background refresh,
 * and `onChange` asks the view to render again when the fresh listing arrives.
 */
export class HookProposalCache {
  private data: HookProposalData = { pending: [], installed: [] };
  private signature = '';
  private running = false;

  constructor(private readonly script: string, private readonly onChange: () => void) {}

  current(roots: string[]): HookProposalData {
    const signature = hookFilesSignature(roots);
    if (signature !== this.signature && !this.running) {
      this.signature = signature;
      this.running = true;
      runHookControl(this.script, { action: 'list', roots })
        .then(answer => {
          if (answer && Array.isArray(answer.pending)) this.data = { pending: answer.pending, installed: answer.installed || [] };
        })
        .catch(error => console.warn('[GravityGuard] Hook proposal listing failed:', error))
        .finally(() => { this.running = false; this.onChange(); });
    }
    return this.data;
  }

  invalidate(): void {
    this.signature = '';
  }
}

/** Splits a proposal or receipt file path into its project root and id; undefined when it is not one. */
export function splitHookFile(file: string): { root: string; id: string } | undefined {
  const id = path.basename(file, '.json');
  for (const dir of [PROPOSALS_DIR, RECEIPTS_DIR]) {
    const folder = path.dirname(file);
    if (folder.toLowerCase().endsWith(dir.toLowerCase())) {
      return { root: folder.slice(0, folder.length - dir.length - 1), id };
    }
  }
  return undefined;
}
