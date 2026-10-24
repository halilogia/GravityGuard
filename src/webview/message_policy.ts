import * as fs from 'fs';
import * as path from 'path';

export function canonicalFile(file: string): string {
  let resolved: string;
  if (fs.existsSync(file)) resolved = fs.realpathSync(file);
  else {
    const parent = path.dirname(file);
    resolved = parent === file ? path.resolve(file) : path.join(canonicalFile(parent), path.basename(file));
  }
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
}

export class MessagePathPolicy {
  private allowed = new Map<string, Set<string>>();
  set(kind: string, files: string[]): void {
    this.allowed.set(kind, new Set(files.map(canonicalFile)));
  }
  permits(kind: string, file: unknown): boolean {
    if (typeof file !== 'string' || !path.isAbsolute(file) || file.includes('\0')) return false;
    try { return this.allowed.get(kind)?.has(canonicalFile(file)) === true; }
    catch { return false; }
  }
}
