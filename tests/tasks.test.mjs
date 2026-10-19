import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  parseTaskMarkdown,
  summarizeTaskItems,
  isUsableConversationId,
  pickConversationId,
  readTaskFile,
  discoverTaskFiles,
  collectTasks,
  countOpenTasks,
  tasksSignature,
  updateTaskItemStatus,
  deleteTaskItem,
  addTaskItem,
  findRecentBrainTaskFiles,
  resolveDefaultTaskFilePath,
  archiveCompletedTasks
} from '../dist/tasks.js';

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'gg-tasks-'));
}

function write(root, rel, content) {
  const p = path.join(root, ...rel.split('/'));
  fs.mkdirSync(path.dirname(p), { recursive: true });
  fs.writeFileSync(p, content);
  return p;
}

test('parseTaskMarkdown maps markers to statuses with 1-based line numbers', () => {
  const items = parseTaskMarkdown('# Plan\n- [ ] open one\n* [/] working\n1. [x] done lower\n- [X] done upper\nplain text\n');
  assert.deepEqual(items.map(i => [i.line, i.status, i.title]), [
    [2, 'open', 'open one'],
    [3, 'in_progress', 'working'],
    [4, 'done', 'done lower'],
    [5, 'done', 'done upper']
  ]);
});

test('parseTaskMarkdown ignores fenced code, strips markup and handles CRLF / BOM / bad input', () => {
  const md = '﻿- [ ] **Bold** `code` task\r\n```\r\n- [ ] inside fence\r\n```\r\n- [x] after fence\r\n';
  const items = parseTaskMarkdown(md);
  assert.deepEqual(items.map(i => i.title), ['Bold code task', 'after fence']);
  assert.equal(items[0].line, 1);
  assert.deepEqual(parseTaskMarkdown(''), []);
  assert.deepEqual(parseTaskMarkdown(undefined), []);
});

test('summarizeTaskItems counts done and total', () => {
  const items = parseTaskMarkdown('- [x] a\n- [ ] b\n- [/] c\n');
  const file = summarizeTaskItems('/x/tasks.md', items);
  assert.equal(file.done, 1);
  assert.equal(file.total, 3);
  assert.equal(file.source, 'file');
  assert.equal(summarizeTaskItems('governance', [], 'governance').source, 'governance');
});

test('isUsableConversationId only accepts plain slug / uuid values', () => {
  assert.equal(isUsableConversationId('abc-123_DEF.1'), true);
  assert.equal(isUsableConversationId('123e4567-e89b-12d3-a456-426614174000'), true);
  for (const bad of ['', '  ', 'default', 'DEFAULT', '../etc', 'a/b', 'a\\b', 'claude:abc', '-lead', null, undefined, 5]) {
    assert.equal(isUsableConversationId(bad), false, `expected unusable: ${String(bad)}`);
  }
});

test('pickConversationId prefers newest event, falls back to session id', () => {
  assert.equal(pickConversationId([{ conversationId: 'newest' }, { conversationId: 'older' }], 'sess'), 'newest');
  assert.equal(pickConversationId([{}, { conversationId: 'second' }], 'sess'), 'second');
  assert.equal(pickConversationId([{ conversationId: 'claude:xyz' }], 'sess'), 'sess');
  assert.equal(pickConversationId([], 'sess'), 'sess');
  assert.equal(pickConversationId(null, 'default'), null);
  assert.equal(pickConversationId(undefined, undefined), null);
});

test('readTaskFile parses a file and returns null for missing paths or directories', () => {
  const root = tmpDir();
  try {
    const p = write(root, 'tasks.md', '- [x] one\n- [ ] two\n');
    const file = readTaskFile(p);
    assert.equal(file.path, p);
    assert.equal(file.done, 1);
    assert.equal(file.total, 2);
    assert.equal(readTaskFile(path.join(root, 'nope.md')), null);
    assert.equal(readTaskFile(root), null);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('discoverTaskFiles finds repo task files and the conversation brain task.md', () => {
  const root = tmpDir();
  const home = tmpDir();
  try {
    write(root, 'tasks.md', '- [ ] repo task\n');
    write(root, '.gravityguard/tasks.md', '- [x] nested\n');
    write(home, '.gemini/antigravity/brain/conv-1/task.md', '- [/] brain task\n');

    const withBrain = discoverTaskFiles([root], { conversationId: 'conv-1', homeDir: home });
    assert.equal(withBrain.length, 3);
    assert.ok(withBrain.some(f => f.path.includes(path.join('brain', 'conv-1'))));

    const withoutBrain = discoverTaskFiles([root], { conversationId: 'default', homeDir: home });
    assert.equal(withoutBrain.length, 2);

    assert.deepEqual(discoverTaskFiles([path.join(root, 'missing')], { homeDir: home }), []);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('discoverTaskFiles lists one physical file once even when two candidate names reach it', () => {
  // On macOS `tasks.md` and `TASKS.md` are the same file; a hard link reproduces that on every platform.
  const root = tmpDir();
  try {
    write(root, 'tasks.md', '- [ ] only task\n');
    fs.mkdirSync(path.join(root, 'docs'), { recursive: true });
    fs.linkSync(path.join(root, 'tasks.md'), path.join(root, 'docs', 'TASKS.md'));
    const files = discoverTaskFiles([root], { homeDir: root });
    assert.equal(files.length, 1, files.map((f) => f.path).join(' | '));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('collectTasks merges files, obligation project roots and governance tasks', () => {
  const root = tmpDir();
  const other = tmpDir();
  const home = tmpDir();
  try {
    write(root, 'task.md', '- [ ] ws task\n');
    write(other, 'tasks.md', '- [x] other root task\n');

    const files = collectTasks({
      workspaceRoot: root,
      obligationMaps: [{ 'a.ts': { project_root: other } }, null],
      govData: {
        tasks: {
          pending: {
            t1: { title: 'gov open', status: 'open' },
            t2: { title: 'gov doing', status: 'in-progress', conversation_id: 'claude:sess' },
            t3: { title: 'foreign', status: 'open', conversation_id: 'someone-else' }
          }
        }
      },
      events: [],
      sessionId: 'sess',
      homeDir: home
    });

    const gov = files.find(f => f.source === 'governance');
    assert.ok(gov);
    assert.deepEqual(gov.items.map(i => i.title), ['gov open', 'gov doing']);
    assert.equal(gov.items[1].status, 'in_progress');
    assert.equal(files.filter(f => f.source === 'file').length, 2);
  } finally {
    for (const d of [root, other, home]) {
      fs.rmSync(d, { recursive: true, force: true });
    }
  }
});

test('collectTasks never throws on empty / malformed input', () => {
  assert.deepEqual(collectTasks({ workspaceRoot: '', govData: { tasks: { pending: [] } } }), []);
  assert.deepEqual(collectTasks({ workspaceRoot: '', govData: 'garbage' }), []);
});

test('countOpenTasks sums open and in-progress items', () => {
  const a = summarizeTaskItems('a', parseTaskMarkdown('- [x] a\n- [ ] b\n- [/] c\n'));
  const b = summarizeTaskItems('b', parseTaskMarkdown('- [x] d\n'));
  assert.equal(countOpenTasks([a, b]), 2);
  assert.equal(countOpenTasks([]), 0);
});

test('tasksSignature changes when items change and is stable otherwise', () => {
  const a = summarizeTaskItems('f', parseTaskMarkdown('- [ ] x\n'));
  const same = summarizeTaskItems('f', parseTaskMarkdown('- [ ] x\n'));
  const changed = summarizeTaskItems('f', parseTaskMarkdown('- [x] x\n'));
  assert.equal(tasksSignature([a]), tasksSignature([same]));
  assert.notEqual(tasksSignature([a]), tasksSignature([changed]));
  assert.match(tasksSignature([]), /^0\./);
});

test('updateTaskItemStatus cycles status between open, in_progress, and done', () => {
  const root = tmpDir();
  try {
    const p = write(root, 'tasks.md', '- [ ] first task\n* [/] second task\n1. [x] third task\n');

    // Cycle first: open -> in_progress
    assert.equal(updateTaskItemStatus(p, 1, 'in_progress'), true);
    let items = parseTaskMarkdown(fs.readFileSync(p, 'utf8'));
    assert.equal(items[0].status, 'in_progress');

    // Cycle first: in_progress -> done
    assert.equal(updateTaskItemStatus(p, 1, 'done'), true);
    items = parseTaskMarkdown(fs.readFileSync(p, 'utf8'));
    assert.equal(items[0].status, 'done');

    // Cycle first: done -> open
    assert.equal(updateTaskItemStatus(p, 1, 'open'), true);
    items = parseTaskMarkdown(fs.readFileSync(p, 'utf8'));
    assert.equal(items[0].status, 'open');

    // Bad line or missing file
    assert.equal(updateTaskItemStatus(p, 99, 'done'), false);
    assert.equal(updateTaskItemStatus(path.join(root, 'missing.md'), 1, 'done'), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('deleteTaskItem removes line and preserves other tasks', () => {
  const root = tmpDir();
  try {
    const p = write(root, 'tasks.md', '- [ ] keep first\n- [x] delete second\n- [/] keep third\n');
    assert.equal(deleteTaskItem(p, 2), true);
    const items = parseTaskMarkdown(fs.readFileSync(p, 'utf8'));
    assert.equal(items.length, 2);
    assert.equal(items[0].title, 'keep first');
    assert.equal(items[1].title, 'keep third');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('addTaskItem appends open task to markdown file', () => {
  const root = tmpDir();
  try {
    const p = write(root, 'tasks.md', '- [x] existing\n');
    assert.equal(addTaskItem(p, 'newly added task'), true);
    const items = parseTaskMarkdown(fs.readFileSync(p, 'utf8'));
    assert.equal(items.length, 2);
    assert.equal(items[1].title, 'newly added task');
    assert.equal(items[1].status, 'open');

    // Empty or whitespace title is rejected
    assert.equal(addTaskItem(p, '   '), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('discoverTaskFiles discovers both tasks.md and task.md in brain folder', () => {
  const root = tmpDir();
  const home = tmpDir();
  try {
    write(home, '.gemini/antigravity/brain/conv-plural/tasks.md', '- [x] plural task\n');
    const files = discoverTaskFiles([root], { conversationId: 'conv-plural', homeDir: home });
    assert.equal(files.length, 1);
    assert.equal(files[0].items[0].title, 'plural task');
    assert.equal(files[0].done, 1);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('findRecentBrainTaskFiles sorts by mtime descending and filters non-directories', () => {
  const home = tmpDir();
  try {
    const p1 = write(home, '.gemini/antigravity/brain/older/tasks.md', '- [ ] older\n');
    const p2 = write(home, '.gemini/antigravity/brain/newer/tasks.md', '- [ ] newer\n');
    // Ensure mtime difference
    fs.utimesSync(p1, new Date('2026-01-01'), new Date('2026-01-01'));
    fs.utimesSync(p2, new Date('2026-06-01'), new Date('2026-06-01'));

    const found = findRecentBrainTaskFiles(home, 2);
    assert.equal(found.length, 2);
    assert.equal(found[0], p2);
    assert.equal(found[1], p1);
  } finally {
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('resolveDefaultTaskFilePath prioritizes workspace, then session brain, then fallback', () => {
  const root = tmpDir();
  const home = tmpDir();
  try {
    assert.equal(resolveDefaultTaskFilePath(root, 'sess-1', home), path.join(root, 'tasks.md'));
    assert.equal(resolveDefaultTaskFilePath('', 'sess-1', home), path.join(home, '.gemini', 'antigravity', 'brain', 'sess-1', 'tasks.md'));
    assert.equal(resolveDefaultTaskFilePath('', 'default', home), path.join(home, 'tasks.md'));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('collectTasks with allowBrainFallback discovers active brain tasks when workspace has no tasks', () => {
  const root = tmpDir();
  const home = tmpDir();
  try {
    write(home, '.gemini/antigravity/brain/active-sess/tasks.md', '- [ ] active brain task\n');
    const files = collectTasks({
      workspaceRoot: root,
      events: [{ conversationId: 'non-existent-conv' }],
      sessionId: 'another-non-existent',
      homeDir: home,
      allowBrainFallback: true
    });
    assert.equal(files.length, 1);
    assert.equal(files[0].items[0].title, 'active brain task');
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
    fs.rmSync(home, { recursive: true, force: true });
  }
});

test('archiveCompletedTasks does not archive when below threshold', () => {
  const root = tmpDir();
  try {
    const taskPath = path.join(root, 'tasks.md');
    fs.writeFileSync(taskPath, '- [ ] open\n- [x] done 1\n- [x] done 2\n', 'utf8');
    const res = archiveCompletedTasks(taskPath, { threshold: 5 });
    assert.equal(res.performed, false);
    assert.equal(res.archivedCount, 0);
    assert.equal(res.retainedDoneCount, 2);
    assert.equal(fs.existsSync(path.join(root, 'taskslog.md')), false);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('archiveCompletedTasks archives older completed tasks and retains recent done items', () => {
  const root = tmpDir();
  try {
    const taskPath = path.join(root, 'tasks.md');
    const lines = [
      '# Sprint Tasks',
      '- [ ] pending task 1',
      '- [/] in progress task',
      '- [x] done 1',
      '- [x] done 2',
      '- [x] done 3',
      '- [x] done 4',
      '- [x] done 5',
      '- [x] done 6',
      '- [x] done 7',
      '- [ ] pending task 2'
    ];
    fs.writeFileSync(taskPath, lines.join('\n') + '\n', 'utf8');

    // Threshold = 5, keepRecentDone = 3. 7 done tasks > 5, so 7 - 3 = 4 should be archived.
    const res = archiveCompletedTasks(taskPath, { threshold: 5, keepRecentDone: 3, dateStr: '2026-10-19' });
    assert.equal(res.performed, true);
    assert.equal(res.archivedCount, 4);
    assert.equal(res.retainedDoneCount, 3);

    // Verify tasks.md contents: done 1..4 removed, done 5..7 kept, pending tasks kept
    const updatedTasks = fs.readFileSync(taskPath, 'utf8');
    assert.ok(!updatedTasks.includes('done 1'));
    assert.ok(!updatedTasks.includes('done 4'));
    assert.ok(updatedTasks.includes('done 5'));
    assert.ok(updatedTasks.includes('done 6'));
    assert.ok(updatedTasks.includes('done 7'));
    assert.ok(updatedTasks.includes('pending task 1'));
    assert.ok(updatedTasks.includes('in progress task'));
    assert.ok(updatedTasks.includes('pending task 2'));

    // Verify taskslog.md contents
    const logPath = path.join(root, 'taskslog.md');
    assert.ok(fs.existsSync(logPath));
    const logContent = fs.readFileSync(logPath, 'utf8');
    assert.ok(logContent.includes('## [2026-10-19]'));
    assert.ok(logContent.includes('- [x] done 1'));
    assert.ok(logContent.includes('- [x] done 4'));
    assert.ok(!logContent.includes('- [x] done 5'));
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});

test('archiveCompletedTasks supports force mode and appends to existing log', () => {
  const root = tmpDir();
  try {
    const taskPath = path.join(root, 'tasks.md');
    fs.writeFileSync(taskPath, '- [x] batch1\n', 'utf8');

    const res1 = archiveCompletedTasks(taskPath, { force: true, dateStr: '2026-10-19' });
    assert.equal(res1.performed, true);
    assert.equal(res1.archivedCount, 1);

    // Add another done item and archive again under same date
    fs.writeFileSync(taskPath, '- [x] batch2\n', 'utf8');
    const res2 = archiveCompletedTasks(taskPath, { force: true, dateStr: '2026-10-19' });
    assert.equal(res2.performed, true);
    assert.equal(res2.archivedCount, 1);

    const logContent = fs.readFileSync(path.join(root, 'taskslog.md'), 'utf8');
    assert.ok(logContent.includes('- [x] batch1'));
    assert.ok(logContent.includes('- [x] batch2'));
    // Ensure date header is not duplicated
    const matches = logContent.match(/## \[2026-10-19\]/g);
    assert.equal(matches.length, 1);
  } finally {
    fs.rmSync(root, { recursive: true, force: true });
  }
});



