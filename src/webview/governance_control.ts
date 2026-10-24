import { spawn } from 'child_process';

export function waiveAdvisory(script: string, roots: string[], target?: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const proc = spawn(process.env.GRAVITYGUARD_PYTHON || 'python', [script], {
      windowsHide: true, stdio: ['pipe', 'pipe', 'pipe']
    });
    const timer = setTimeout(() => { proc.kill(); reject(new Error('Governance command timed out')); }, 15000);
    proc.on('error', error => { clearTimeout(timer); reject(error); });
    proc.on('close', code => { clearTimeout(timer); code === 0 ? resolve() : reject(new Error('Governance command failed')); });
    proc.stdin.on('error', () => { /* Exit status reports a failed engine write. */ });
    proc.stdout.resume(); proc.stderr.resume();
    proc.stdin.end(JSON.stringify({ roots, target }));
  });
}
