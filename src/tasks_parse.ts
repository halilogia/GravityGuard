// Task types and markdown checkbox parsing (split from tasks.ts; re-exported there).

export type TaskStatus = 'open' | 'in_progress' | 'done';

export interface TaskItem {
  /** 1-based line number inside the task file (absent for governance tasks). */
  line?: number;
  title: string;
  status: TaskStatus;
}

/** `path` value used for the governance.json task source (it is not a file path). */
export const GOVERNANCE_TASK_SOURCE = 'governance';

export interface TaskFile {
  /** Absolute file path, or GOVERNANCE_TASK_SOURCE for tasks recorded in governance.json. */
  path: string;
  source: 'file' | 'governance';
  items: TaskItem[];
  done: number;
  total: number;
}

export interface DiscoverTaskOptions {
  /** Active conversation id; adds ~/.gemini/antigravity/brain/<id>/task.md when usable. */
  conversationId?: string | null;
  /** Home directory override (tests); defaults to os.homedir(). */
  homeDir?: string;
  /** Active editor file path in the IDE, if any. */
  activeEditorPath?: string | null;
}

/** Task file locations probed for every project root, in priority order. */
export const TASK_FILE_RELATIVE_PATHS: readonly string[] = [
  'tasks.md',
  'task.md',
  'TASKS.md',
  'TASK.md',
  'docs/tasks.md',
  'docs/TASKS.md',
  '.gravityguard/tasks.md',
  '.gravityguard/runtime/tasks.md'
];

// Same rule as the engine: bullet or ordered-list marker, then [ ] / [/] / [x] / [X], then a title.
export const TASK_LINE_RE = /^\s*(?:[-*+]|\d+\.)\s*\[( |\/|x|X)\]\s+(.+)$/;
export const FENCE_RE = /^\s*```/;
// Guard against pathological files; the webview re-reads task files on every poll.
export const MAX_TASK_FILE_BYTES = 1024 * 1024;

export function statusFromMarker(marker: string): TaskStatus {
  if (marker === '/') {
    return 'in_progress';
  }
  if (marker === 'x' || marker === 'X') {
    return 'done';
  }
  return 'open';
}

export function cleanTitle(raw: string): string {
  const cleaned = raw.replace(/\*\*/g, '').replace(/`/g, '').trim();
  return cleaned || raw.trim();
}

/**
 * Extracts checkbox items from markdown. Lines inside ``` fenced code blocks are ignored.
 * Items with an empty title are skipped.
 */
export function parseTaskMarkdown(content: string): TaskItem[] {
  const items: TaskItem[] = [];
  if (typeof content !== 'string' || content.length === 0) {
    return items;
  }
  const lines = content.replace(/^﻿/, '').split(/\r?\n/);
  let inFence = false;
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
    if (!m) {
      continue;
    }
    const title = cleanTitle(m[2]);
    if (!title) {
      continue;
    }
    items.push({ line: i + 1, title, status: statusFromMarker(m[1]) });
  }
  return items;
}

/** Builds a TaskFile summary from already parsed items. */
export function summarizeTaskItems(
  filePath: string,
  items: TaskItem[],
  source: 'file' | 'governance' = 'file'
): TaskFile {
  return {
    path: filePath,
    source,
    items,
    done: items.filter(item => item.status === 'done').length,
    total: items.length
  };
}
