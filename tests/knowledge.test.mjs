import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import {
  parseKnowledgeMarkdown,
  parseChangelogMarkdown,
  discoverKnowledgeFiles,
  collectMemoryHubData,
  addAdrItem,
  addChangelogItem
} from '../dist/knowledge.js';

function tmpDir() {
  return fs.mkdtempSync(path.join(os.tmpdir(), 'gg-knowledge-'));
}

test('parseKnowledgeMarkdown extracts ADR items with status, title, and decision fields', () => {
  const content = `# Project Architecture

### ADR-001: SQLite FTS5 Hafıza Motoru
- **Durum:** Kabul Edildi
- **Tarih:** 2026-10-15
- **Bağlam:** Hızlı tam metin arama ihtiyacı.
- **Karar:** SQLite FTS5 BM25 entegrasyonu seçildi.
- **Sonuçlar:** 0 MB harici bağımlılık, 1ms sorgu süresi.

### ADR-002: Tarayıcı Otomasyon İzolasyonu
- **Durum:** Öneri
- **Karar:** CDP port 9222 üzerinden izole sekme yönetimi.

### [ADR-003] Düz Metin Basımı
- **Status:** Rejected
- **Karar:** Düz metin yerine akıllı kartlar kullanılmalı.
`;

  const { adrs } = parseKnowledgeMarkdown(content);
  assert.equal(adrs.length, 3);

  assert.equal(adrs[0].id, 'ADR-001');
  assert.equal(adrs[0].title, 'SQLite FTS5 Hafıza Motoru');
  assert.equal(adrs[0].status, 'ACCEPTED');
  assert.equal(adrs[0].decision, 'SQLite FTS5 BM25 entegrasyonu seçildi.');
  assert.equal(adrs[0].context, 'Hızlı tam metin arama ihtiyacı.');
  assert.equal(adrs[0].consequences, '0 MB harici bağımlılık, 1ms sorgu süresi.');

  assert.equal(adrs[1].id, 'ADR-002');
  assert.equal(adrs[1].status, 'PROPOSED');

  assert.equal(adrs[2].id, 'ADR-003');
  assert.equal(adrs[2].status, 'REJECTED');
});

test('parseKnowledgeMarkdown extracts gotchas from bullet [!], callouts, and gotchas section', () => {
  const content = `# Architecture

- [!] Diske doğrudan büyük log yazma, hafızada tut.
> [!WARNING] Token sınırına dikkat edilmeli, alt ajanları kısıtla.

## Kör Noktalar & Dersler
- Regex ile katı markdown parse etme, toleranslı AST kullan.
- [ ] Bu normal bir görevdir gotcha değildir.
`;

  const { gotchas } = parseKnowledgeMarkdown(content);
  assert.equal(gotchas.length, 3);
  assert.match(gotchas[0].text, /Diske doğrudan/);
  assert.match(gotchas[1].text, /Token sınırına/);
  assert.match(gotchas[2].text, /Regex ile katı markdown/);
});

test('parseKnowledgeMarkdown handles empty or malformed markdown safely', () => {
  assert.deepEqual(parseKnowledgeMarkdown(''), { adrs: [], gotchas: [] });
  assert.deepEqual(parseKnowledgeMarkdown('   \n\n  '), { adrs: [], gotchas: [] });
  assert.deepEqual(parseKnowledgeMarkdown(null), { adrs: [], gotchas: [] });
  assert.deepEqual(parseKnowledgeMarkdown(undefined), { adrs: [], gotchas: [] });
});

test('parseChangelogMarkdown extracts unreleased items and latest release summary', () => {
  const changelog = `# Changelog

## [Unreleased]
- Added: Knowledge & ADR Hub sekmesi entegre edildi.
- Fixed: Tasks üst hızlı ekleme çubuğu temizleme hatası.

## [1.4.12] - 2026-10-15
- Added: Active Antigravity brain auto-discovery.
- Fixed: Tasks sekmesi boş durum yönetimi.

## [1.4.11] - 2026-10-14
- Initial interactive tasks release.
`;

  const { unreleased, latestRelease, totalReleases } = parseChangelogMarkdown(changelog);

  assert.equal(unreleased.length, 2);
  assert.match(unreleased[0], /Knowledge & ADR Hub/);
  assert.match(unreleased[1], /Tasks üst hızlı ekleme/);

  assert.ok(latestRelease);
  assert.equal(latestRelease.version, '1.4.12');
  assert.equal(latestRelease.date, '2026-10-15');
  assert.equal(latestRelease.changes.length, 2);
  assert.equal(totalReleases, 2);
});

test('discoverKnowledgeFiles detects KNOWLEDGE.md and CHANGELOG.md in workspace root', () => {
  const dir = tmpDir();
  fs.writeFileSync(path.join(dir, 'KNOWLEDGE.md'), '# Knowledge\n');
  fs.writeFileSync(path.join(dir, 'CHANGELOG.md'), '# Changelog\n');

  const { knowledgePath, changelogPath } = discoverKnowledgeFiles({ workspaceRoot: dir });
  assert.equal(knowledgePath, path.join(dir, 'KNOWLEDGE.md'));
  assert.equal(changelogPath, path.join(dir, 'CHANGELOG.md'));
});

test('addAdrItem appends an ADR block with automatic next ID', () => {
  const dir = tmpDir();
  const kFile = path.join(dir, 'KNOWLEDGE.md');
  fs.writeFileSync(kFile, '### ADR-001: İlk Karar\n- **Karar:** A seçildi.\n');

  const ok = addAdrItem(kFile, {
    title: 'Yeni Mimari Karar',
    decision: 'B seçildi çünkü daha hızlı.',
    status: 'ACCEPTED'
  });

  assert.equal(ok, true);
  const updated = fs.readFileSync(kFile, 'utf8');
  assert.match(updated, /### ADR-002: Yeni Mimari Karar/);
  assert.match(updated, /B seçildi çünkü daha hızlı/);
});

test('addChangelogItem inserts bullet directly under [Unreleased]', () => {
  const dir = tmpDir();
  const cFile = path.join(dir, 'CHANGELOG.md');
  fs.writeFileSync(cFile, '# Changelog\n\n## [Unreleased]\n- Added: Önceki madde\n\n## [1.0.0]\n- Initial\n');

  const ok = addChangelogItem(cFile, 'Added: İkinci madde eklendi');
  assert.equal(ok, true);

  const updated = fs.readFileSync(cFile, 'utf8');
  const lines = updated.split(/\r?\n/);
  const unreleasedIdx = lines.findIndex(l => l.includes('[Unreleased]'));
  assert.equal(lines[unreleasedIdx + 1], '- Added: İkinci madde eklendi');
  assert.equal(lines[unreleasedIdx + 2], '- Added: Önceki madde');
});

test('collectMemoryHubData aggregates both knowledge and changelog files', () => {
  const dir = tmpDir();
  fs.writeFileSync(path.join(dir, 'KNOWLEDGE.md'), '### ADR-001: Test\n- **Karar:** Evet\n');
  fs.writeFileSync(path.join(dir, 'CHANGELOG.md'), '## [Unreleased]\n- Fixed: Test hatası\n');

  const hub = collectMemoryHubData({ workspaceRoot: dir });
  assert.ok(hub.knowledge);
  assert.equal(hub.knowledge.totalAdrs, 1);
  assert.ok(hub.changelog);
  assert.equal(hub.changelog.unreleased.length, 1);
});
