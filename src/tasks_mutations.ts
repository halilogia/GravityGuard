// Task file mutations: status toggle, archive, delete, add (split from tasks.ts; re-exported there).
import * as fs from 'fs';
import * as path from 'path';
import { FENCE_RE, TASK_LINE_RE, TaskStatus } from './tasks_parse';

/**
 * Updates the checkbox marker on the specified 1-based line of a markdown task file.
 * Preserves line endings (CRLF / LF).
 */
export function updateTaskItemStatus(filePath: string, line: number, nextStatus: TaskStatus): boolean {
  try {
    if (!fs.existsSync(filePath)) {
      return false;
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    const isCrlf = raw.includes('\r\n');
    const lines = raw.split(/\r?\n/);
    const idx = line - 1;
    if (idx < 0 || idx >= lines.length) {
      return false;
    }
    const currentLine = lines[idx];
    const marker = nextStatus === 'done' ? 'x' : nextStatus === 'in_progress' ? '/' : ' ';
    const updatedLine = currentLine.replace(/^(\s*(?:[-*+]|\d+\.)\s*\[)(?: |\/|x|X)(\]\s+.*)$/, `$1${marker}$2`);
    if (updatedLine === currentLine) {
      return false;
    }
    lines[idx] = updatedLine;
    fs.writeFileSync(filePath, lines.join(isCrlf ? '\r\n' : '\n'), 'utf8');

    // Auto-archive trigger: When a task is marked as done, evaluate thresholds
    if (nextStatus === 'done') {
      try {
        archiveCompletedTasks(filePath, { threshold: 10, keepRecentDone: 5, maxLines: 150 });
      } catch (archiveErr) {
        console.debug('[GravityGuard] Auto-archive error (non-fatal):', archiveErr);
      }
    }

    return true;
  } catch (err) {
    console.error(`[GravityGuard] Failed to update task status in ${filePath}:`, err);
    return false;
  }
}

/**
 * Options for archiving completed tasks from a markdown task file.
 */
export interface TaskArchiveOptions {
  /** Minimum number of completed tasks to trigger archive. Default: 10 */
  threshold?: number;
  /** Maximum lines before triggering archive. Default: 150 */
  maxLines?: number;
  /** Number of most recent completed tasks to retain in tasks.md for context. Default: 5 */
  keepRecentDone?: number;
  /** If true, archive immediately regardless of threshold. Default: false */
  force?: boolean;
  /** Date string for the archive heading (YYYY-MM-DD). */
  dateStr?: string;
  /** Custom archive file name. Default: 'taskslog.md' */
  logFileName?: string;
}

export interface TaskArchiveResult {
  archivedCount: number;
  retainedDoneCount: number;
  tasksLogPath: string;
  performed: boolean;
}

/**
 * Archives completed tasks ([x]) from a markdown task file into taskslog.md.
 * Keeps recent completed tasks for continuity while keeping tasks.md compact and compliant.
 */
export function archiveCompletedTasks(filePath: string, options?: TaskArchiveOptions): TaskArchiveResult {
  try {
    if (!fs.existsSync(filePath)) {
      return { archivedCount: 0, retainedDoneCount: 0, tasksLogPath: '', performed: false };
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    const isCrlf = raw.includes('\r\n');
    const lines = raw.split(/\r?\n/);

    const threshold = options?.threshold ?? 10;
    const maxLines = options?.maxLines ?? 150;
    const keepRecentDone = options?.keepRecentDone ?? 5;
    const force = options?.force ?? false;
    const logFileName = options?.logFileName ?? 'taskslog.md';

    let inFence = false;
    const doneIndices: number[] = [];
    for (let i = 0; i < lines.length; i++) {
      const text = lines[i];
      if (FENCE_RE.test(text)) {
        inFence = !inFence;
        continue;
      }
      if (inFence) {
        continue;
      }
      const m = TASK_LINE_RE.exec(text);
      if (m && (m[1] === 'x' || m[1] === 'X')) {
        doneIndices.push(i);
      }
    }

    const totalDone = doneIndices.length;
    const totalLines = lines.length;
    const shouldArchive = force || (totalDone > threshold) || (totalLines > maxLines && totalDone > keepRecentDone);

    if (!shouldArchive) {
      return { archivedCount: 0, retainedDoneCount: totalDone, tasksLogPath: '', performed: false };
    }

    const keepCount = Math.max(0, keepRecentDone);
    let archiveCount = 0;
    if (totalDone <= keepCount) {
      if (!force) {
        return { archivedCount: 0, retainedDoneCount: totalDone, tasksLogPath: '', performed: false };
      }
      archiveCount = totalDone;
    } else {
      archiveCount = totalDone - keepCount;
    }

    if (archiveCount <= 0) {
      return { archivedCount: 0, retainedDoneCount: totalDone, tasksLogPath: '', performed: false };
    }

    const toArchiveSet = new Set(doneIndices.slice(0, archiveCount));
    const archivedLines = doneIndices.slice(0, archiveCount).map(idx => lines[idx]);
    const remainingLines = lines.filter((_, idx) => !toArchiveSet.has(idx));

    const dir = path.dirname(filePath);
    const logPath = path.join(dir, logFileName);
    const today = options?.dateStr || new Date().toISOString().slice(0, 10);

    let logContent = '';
    if (fs.existsSync(logPath)) {
      logContent = fs.readFileSync(logPath, 'utf8');
    }

    if (!logContent.trim()) {
      logContent = '# 📜 Tasks Log (Görev Arşivi)\n\n> Bu dosya GravityGuard Task Archiver tarafından otomatik yönetilir.\n> tasks.md dosyasının şişmesini önlemek için tamamlanan görevler buraya aktarılır.\n';
    }

    const dateHeader = `## [${today}]`;
    const archivedBlock = archivedLines.join('\n');

    if (logContent.includes(dateHeader)) {
      const parts = logContent.split(dateHeader);
      logContent = parts[0] + dateHeader + '\n' + archivedBlock + '\n' + parts[1].replace(/^\r?\n/, '');
    } else {
      if (!logContent.endsWith('\n\n')) {
        logContent = logContent.replace(/\s*$/, '\n\n');
      }
      logContent += `${dateHeader}\n${archivedBlock}\n`;
    }

    fs.writeFileSync(logPath, logContent, 'utf8');
    const newline = isCrlf ? '\r\n' : '\n';
    fs.writeFileSync(filePath, remainingLines.join(newline), 'utf8');

    return {
      archivedCount: archivedLines.length,
      retainedDoneCount: totalDone - archivedLines.length,
      tasksLogPath: logPath,
      performed: true
    };
  } catch (err) {
    console.error(`[GravityGuard] Failed to archive tasks in ${filePath}:`, err);
    return { archivedCount: 0, retainedDoneCount: 0, tasksLogPath: '', performed: false };
  }
}

/**
 * Deletes the specified 1-based line from a markdown task file.
 * Preserves line endings.
 */
export function deleteTaskItem(filePath: string, line: number): boolean {
  try {
    if (!fs.existsSync(filePath)) {
      return false;
    }
    const raw = fs.readFileSync(filePath, 'utf8');
    const isCrlf = raw.includes('\r\n');
    const lines = raw.split(/\r?\n/);
    const idx = line - 1;
    if (idx < 0 || idx >= lines.length) {
      return false;
    }
    lines.splice(idx, 1);
    fs.writeFileSync(filePath, lines.join(isCrlf ? '\r\n' : '\n'), 'utf8');
    return true;
  } catch (err) {
    console.error(`[GravityGuard] Failed to delete task in ${filePath}:`, err);
    return false;
  }
}

/**
 * Appends a new open task item to a markdown task file.
 */
export function addTaskItem(filePath: string, title: string): boolean {
  try {
    const trimmed = title.trim();
    if (!trimmed) {
      return false;
    }
    let raw = '';
    let isCrlf = false;
    if (fs.existsSync(filePath)) {
      raw = fs.readFileSync(filePath, 'utf8');
      isCrlf = raw.includes('\r\n');
    } else {
      const dir = path.dirname(filePath);
      if (!fs.existsSync(dir)) {
        fs.mkdirSync(dir, { recursive: true });
      }
    }
    const newline = isCrlf ? '\r\n' : '\n';
    const cleanRaw = raw.endsWith('\n') ? raw : (raw ? raw + newline : '');
    const newLineContent = `- [ ] ${trimmed}${newline}`;
    fs.writeFileSync(filePath, cleanRaw + newLineContent, 'utf8');
    return true;
  } catch (err) {
    console.error(`[GravityGuard] Failed to add task in ${filePath}:`, err);
    return false;
  }
}
