// Task checklist discovery and markdown checkbox parsing for the Tasks tab.
// Pure Node module (no vscode import) so it can be unit-tested from dist/ and shares its rules with the engine.
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

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
const TASK_LINE_RE = /^\s*(?:[-*+]|\d+\.)\s*\[( |\/|x|X)\]\s+(.+)$/;
const FENCE_RE = /^\s*```/;
// Guard against pathological files; the webview re-reads task files on every poll.
const MAX_TASK_FILE_BYTES = 1024 * 1024;

function statusFromMarker(marker: string): TaskStatus {
  if (marker === '/') {
    return 'in_progress';
  }
  if (marker === 'x' || marker === 'X') {
    return 'done';
  }
  return 'open';
}

function cleanTitle(raw: string): string {
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

/**
 * Conversation ids become a directory name under the brain folder, so only plain
 * slugs / UUIDs are accepted ("default" and prefixed ids such as "claude:<uuid>" are not brain folders).
 */
export function isUsableConversationId(id: unknown): id is string {
  if (typeof id !== 'string') {
    return false;
  }
  const value = id.trim();
  if (!value || value.toLowerCase() === 'default' || value.includes('..')) {
    return false;
  }
  return /^[A-Za-z0-9][A-Za-z0-9._-]*$/.test(value);
}

/**
 * Picks the conversation whose brain folder should be probed: the conversationId of the most recent
 * event (events are newest first), falling back to the governance session id.
 * Returns null when neither is a usable brain folder name.
 */
export function pickConversationId(
  events: ReadonlyArray<{ conversationId?: unknown } | null | undefined> | null | undefined,
  sessionId?: string | null,
  homeDir?: string
): string | null {
  const brainExists = (id: string): boolean => {
    if (!homeDir) {
      return true;
    }
    try {
      return fs.existsSync(path.join(homeDir, '.gemini', 'antigravity', 'brain', id));
    } catch {
      return false;
    }
  };

  if (Array.isArray(events)) {
    for (const ev of events) {
      const id = ev?.conversationId;
      if (typeof id === 'string' && id.trim() !== '') {
        const trimmed = id.trim();
        if (isUsableConversationId(trimmed) && brainExists(trimmed)) {
          return trimmed;
        }
      }
    }
  }
  if (isUsableConversationId(sessionId)) {
    const trimmed = sessionId.trim();
    if (brainExists(trimmed)) {
      return trimmed;
    }
  }
  return null;
}

/**
 * Conversation the monitor currently follows, as recorded (agent prefixes such as `claude:` are kept):
 * the conversationId of the newest event (events are newest first), else the governance session id.
 * "default" / empty values mean "unknown" and yield null. Unlike pickConversationId this value is only
 * used to match governance tasks, not to build a brain folder path.
 */
export function pickActiveConversationId(
  events: ReadonlyArray<{ conversationId?: unknown } | null | undefined> | null | undefined,
  sessionId?: string | null
): string | null {
  const usable = (value: unknown): string | null => {
    if (typeof value !== 'string') {
      return null;
    }
    const trimmed = value.trim();
    return trimmed && trimmed.toLowerCase() !== 'default' ? trimmed : null;
  };
  if (Array.isArray(events)) {
    for (const ev of events) {
      const id = usable(ev?.conversationId);
      if (id) {
        return id;
      }
    }
  }
  return usable(sessionId);
}

/** Drops the `claude:` / `codex:` agent prefix so ids from different writers compare equal. */
function stripConversationPrefix(id: string): string {
  return id.trim().replace(/^(?:claude|codex):/i, '');
}

function normalizeTaskStatus(value: unknown): TaskStatus {
  const key = typeof value === 'string' ? value.trim().toLowerCase().replace(/[\s-]+/g, '_') : '';
  if (key === 'in_progress' || key === 'inprogress' || key === 'doing' || key === 'active') {
    return 'in_progress';
  }
  if (key === 'done' || key === 'completed' || key === 'complete' || key === 'closed') {
    return 'done';
  }
  return 'open';
}

/**
 * Tasks recorded by the engine in governance.json under `tasks.pending`
 * (`{id: {title, status, conversation_id?, timestamp?}}`).
 * Entries bound to another conversation are skipped when the active conversation is known;
 * entries without a conversation_id always apply. Returns null when the schema is absent or empty.
 */
export function governanceTaskFile(govData: unknown, activeConversationId?: string | null): TaskFile | null {
  const pending = (govData as { tasks?: { pending?: unknown } } | null | undefined)?.tasks?.pending;
  if (!pending || typeof pending !== 'object' || Array.isArray(pending)) {
    return null;
  }
  const active = typeof activeConversationId === 'string' && activeConversationId.trim() !== ''
    ? stripConversationPrefix(activeConversationId)
    : null;

  const items: TaskItem[] = [];
  for (const record of Object.values(pending as Record<string, unknown>)) {
    if (!record || typeof record !== 'object') {
      continue;
    }
    const entry = record as Record<string, unknown>;
    if (typeof entry.title !== 'string') {
      continue;
    }
    const title = cleanTitle(entry.title);
    if (!title) {
      continue;
    }
    const entryConversation = typeof entry.conversation_id === 'string' ? entry.conversation_id.trim() : '';
    if (entryConversation && active && stripConversationPrefix(entryConversation) !== active) {
      continue;
    }
    items.push({ title, status: normalizeTaskStatus(entry.status) });
  }
  if (items.length === 0) {
    return null;
  }
  return summarizeTaskItems(GOVERNANCE_TASK_SOURCE, items, 'governance');
}

/**
 * Project roots to scan: the open workspace first, then every distinct `project_root`
 * recorded on pending obligations (bounded to keep per-poll I/O small).
 */
export function collectTaskRoots(
  workspaceRoot: string,
  obligationMaps: ReadonlyArray<Record<string, any> | null | undefined>,
  maxRoots: number = 8
): string[] {
  const roots: string[] = [];
  const seen = new Set<string>();
  const add = (candidate: unknown): void => {
    if (roots.length >= maxRoots || typeof candidate !== 'string' || candidate.trim() === '') {
      return;
    }
    const key = normalizeKey(candidate);
    if (!seen.has(key)) {
      seen.add(key);
      roots.push(candidate);
    }
  };

  add(workspaceRoot);
  for (const map of obligationMaps) {
    if (!map || typeof map !== 'object') {
      continue;
    }
    for (const record of Object.values(map)) {
      if (record && typeof record === 'object') {
        add((record as Record<string, unknown>).project_root);
      }
    }
  }
  return roots;
}

function normalizeKey(p: string): string {
  const resolved = path.resolve(p);
  return process.platform === 'win32' ? resolved.toLowerCase() : resolved;
}

/**
 * Scans ~/.gemini/antigravity/brain/ for directories containing tasks.md or task.md,
 * sorted by modification time (newest first).
 */
export function findRecentBrainTaskFiles(homeDir: string = os.homedir(), limit: number = 3): string[] {
  const brainDir = path.join(homeDir, '.gemini', 'antigravity', 'brain');
  if (!fs.existsSync(brainDir)) {
    return [];
  }
  try {
    const entries = fs.readdirSync(brainDir, { withFileTypes: true });
    const candidates: Array<{ path: string; mtime: number }> = [];
    for (const entry of entries) {
      if (!entry.isDirectory() || !isUsableConversationId(entry.name)) {
        continue;
      }
      for (const taskName of ['tasks.md', 'task.md', 'TASKS.md']) {
        const fullPath = path.join(brainDir, entry.name, taskName);
        try {
          const stat = fs.statSync(fullPath);
          if (stat.isFile() && stat.size <= MAX_TASK_FILE_BYTES) {
            candidates.push({ path: fullPath, mtime: stat.mtimeMs });
            break;
          }
        } catch {
          // ignore unreadable
        }
      }
    }
    candidates.sort((a, b) => b.mtime - a.mtime);
    return candidates.slice(0, limit).map(c => c.path);
  } catch {
    return [];
  }
}

/**
 * Resolves the default target file path to create/append tasks when creating the first task.
 */
export function resolveDefaultTaskFilePath(
  workspaceRoot?: string,
  sessionId?: string | null,
  homeDir: string = os.homedir()
): string {
  if (workspaceRoot && typeof workspaceRoot === 'string' && workspaceRoot.trim() !== '') {
    return path.join(workspaceRoot.trim(), 'tasks.md');
  }
  if (isUsableConversationId(sessionId) && homeDir) {
    const brainFolder = path.join(homeDir, '.gemini', 'antigravity', 'brain', sessionId.trim());
    return path.join(brainFolder, 'tasks.md');
  }
  if (homeDir) {
    const recent = findRecentBrainTaskFiles(homeDir, 1);
    if (recent.length > 0) {
      return recent[0];
    }
    const brainDir = path.join(homeDir, '.gemini', 'antigravity', 'brain');
    try {
      if (fs.existsSync(brainDir)) {
        const dirs = fs.readdirSync(brainDir, { withFileTypes: true })
          .filter(d => d.isDirectory() && isUsableConversationId(d.name))
          .map(d => ({
            name: d.name,
            mtime: fs.statSync(path.join(brainDir, d.name)).mtimeMs
          }))
          .sort((a, b) => b.mtime - a.mtime);
        if (dirs.length > 0) {
          return path.join(brainDir, dirs[0].name, 'tasks.md');
        }
      }
    } catch {
      // fallback
    }
    return path.join(homeDir, 'tasks.md');
  }
  return path.resolve('tasks.md');
}

/** Ordered, de-duplicated list of task file paths that may exist for the given roots / conversation. */
export function taskFileCandidates(
  projectRoots: readonly string[],
  conversationId?: string | null,
  homeDir: string = os.homedir(),
  activeEditorPath?: string | null
): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  const add = (candidate: string): void => {
    const key = normalizeKey(candidate);
    if (!seen.has(key)) {
      seen.add(key);
      result.push(candidate);
    }
  };

  if (activeEditorPath && typeof activeEditorPath === 'string' && activeEditorPath.trim() !== '') {
    const lower = activeEditorPath.toLowerCase();
    if (lower.endsWith('.md')) {
      const base = path.basename(lower);
      if (base === 'tasks.md' || base === 'task.md' || lower.includes('brain')) {
        add(activeEditorPath.trim());
      }
    }
  }

  for (const root of projectRoots) {
    if (typeof root !== 'string' || root.trim() === '') {
      continue;
    }
    for (const rel of TASK_FILE_RELATIVE_PATHS) {
      add(path.join(root, ...rel.split('/')));
    }
  }

  if (isUsableConversationId(conversationId) && homeDir) {
    add(path.join(homeDir, '.gemini', 'antigravity', 'brain', conversationId.trim(), 'tasks.md'));
    add(path.join(homeDir, '.gemini', 'antigravity', 'brain', conversationId.trim(), 'task.md'));
  }
  return result;
}

/** Reads and parses one task file; returns null when it is missing, unreadable or not a regular file. */
export function readTaskFile(filePath: string): TaskFile | null {
  try {
    const stat = fs.statSync(filePath);
    if (!stat.isFile() || stat.size > MAX_TASK_FILE_BYTES) {
      return null;
    }
    const content = fs.readFileSync(filePath, 'utf8');
    return summarizeTaskItems(filePath, parseTaskMarkdown(content));
  } catch {
    return null;
  }
}

/**
 * Finds and parses every existing task file for the given project roots (and conversation brain folder).
 * Unreadable files are skipped silently.
 */
export function discoverTaskFiles(projectRoots: readonly string[], options: DiscoverTaskOptions = {}): TaskFile[] {
  const files: TaskFile[] = [];
  for (const candidate of taskFileCandidates(projectRoots, options.conversationId, options.homeDir, options.activeEditorPath)) {
    const file = readTaskFile(candidate);
    if (file) {
      files.push(file);
    }
  }
  return files;
}

export interface CollectTasksInput {
  /** Open workspace (or auto-discovered project) root; may be empty. */
  workspaceRoot: string;
  /** Pending obligation maps whose records may carry `project_root`. */
  obligationMaps?: ReadonlyArray<Record<string, any> | null | undefined>;
  /** Parsed governance.json (for `tasks.pending`); may be null. */
  govData?: unknown;
  /** Live log events, newest first (for the active conversation id). */
  events?: ReadonlyArray<{ conversationId?: unknown } | null | undefined> | null;
  /** Governance session id fallback; the "active" placeholder must be passed as null. */
  sessionId?: string | null;
  /** Home directory override (tests). */
  homeDir?: string;
  /** Active editor file path in the IDE, if any. */
  activeEditorPath?: string | null;
  /** When true, scans ~/.gemini/antigravity/brain/ for the newest task file if no files found. */
  allowBrainFallback?: boolean;
}

/**
 * Single entry point for the Tasks tab: markdown task files of every project root (plus the active
 * Antigravity brain folder) followed by the governance.json task source. Never throws.
 */
export function collectTasks(input: CollectTasksInput): TaskFile[] {
  const sources: TaskFile[] = [];
  const home = input.homeDir ?? os.homedir();
  try {
    const roots = collectTaskRoots(input.workspaceRoot, input.obligationMaps ?? []);
    const brainConversation = pickConversationId(input.events, input.sessionId, home);
    sources.push(...discoverTaskFiles(roots, {
      conversationId: brainConversation,
      homeDir: home,
      activeEditorPath: input.activeEditorPath
    }));

    // Fallback: If no markdown task files were found from roots or brainConversation,
    // look for the most recently modified brain task file in ~/.gemini/antigravity/brain/*/
    if (input.allowBrainFallback && sources.filter(f => f.source === 'file').length === 0 && home) {
      const recentBrainFiles = findRecentBrainTaskFiles(home, 1);
      for (const candidate of recentBrainFiles) {
        const file = readTaskFile(candidate);
        if (file) {
          sources.push(file);
        }
      }
    }
  } catch {
    // unreadable task files must never break the monitor
  }
  try {
    const governance = governanceTaskFile(input.govData, pickActiveConversationId(input.events, input.sessionId));
    if (governance) {
      sources.push(governance);
    }
  } catch {
    // malformed governance schema is ignored
  }
  return sources;
}

/** Number of tasks that are not finished yet (open + in progress). */
export function countOpenTasks(files: readonly TaskFile[]): number {
  let open = 0;
  for (const file of files) {
    open += file.total - file.done;
  }
  return open;
}

/** Compact change signature so the webview can detect task edits cheaply between polls. */
export function tasksSignature(files: readonly TaskFile[]): string {
  let hash = 5381;
  const feed = (text: string): void => {
    for (let i = 0; i < text.length; i++) {
      hash = ((hash << 5) + hash + text.charCodeAt(i)) | 0;
    }
  };
  for (const file of files) {
    feed(file.path);
    for (const item of file.items) {
      feed(`|${item.line ?? ''}:${item.status}:${item.title}`);
    }
  }
  return `${files.length}.${(hash >>> 0).toString(36)}`;
}

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
    return true;
  } catch (err) {
    console.error(`[GravityGuard] Failed to update task status in ${filePath}:`, err);
    return false;
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
