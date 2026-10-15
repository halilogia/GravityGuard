// Knowledge Hub (ADR, Kör Noktalar & CHANGELOG takibi) veri motoru.
// Saf Node modülü (vscode bağımlılığı yoktur, dist/ üzerinden doğrudan birim testten geçer).
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';

export type AdrStatus = 'ACCEPTED' | 'PROPOSED' | 'SUPERSEDED' | 'REJECTED' | 'DEPRECATED';

export interface AdrItem {
  id: string; // örn: "ADR-001"
  title: string; // örn: "SQLite FTS5 Hafıza Motoru"
  status: AdrStatus;
  statusLabel?: string;
  context?: string;
  decision?: string;
  consequences?: string;
  line: number;
}

export interface GotchaItem {
  text: string;
  line: number;
}

export interface KnowledgeFile {
  path: string;
  adrs: AdrItem[];
  gotchas: GotchaItem[];
  totalAdrs: number;
  totalGotchas: number;
}

export interface ChangelogRelease {
  version: string; // örn: "1.4.12"
  date?: string; // örn: "2026-10-15"
  changes: string[]; // özet maddeler
  line: number;
}

export interface ChangelogFile {
  path: string;
  unreleased: string[]; // henüz yayınlanmamış değişiklikler
  latestRelease?: ChangelogRelease;
  totalReleases: number;
}

export interface MemoryHubData {
  knowledge?: KnowledgeFile;
  changelog?: ChangelogFile;
}

export const KNOWLEDGE_CANDIDATE_PATHS: readonly string[] = [
  'KNOWLEDGE.md',
  'knowledge.md',
  'docs/KNOWLEDGE.md',
  'docs/knowledge.md',
  '.gravityguard/KNOWLEDGE.md',
  '.gravityguard/runtime/KNOWLEDGE.md'
];

export const CHANGELOG_CANDIDATE_PATHS: readonly string[] = [
  'CHANGELOG.md',
  'changelog.md',
  'docs/CHANGELOG.md',
  'docs/changelog.md'
];

const ADR_HEADER_RE = /^(?:#{2,4})\s+(?:\[?(ADR[-_ ]?\d+)\]?[:.]?\s*)(.+)$/i;
const GOTCHA_LINE_RE = /^\s*[-*+]\s+\[!\]\s+(.+)$/;
const CALLOUT_WARNING_RE = /^>\s*\[!(?:WARNING|CAUTION|DANGER|ALERT)\]\s*(.*)$/i;
const UNRELEASED_HEADER_RE = /^#{2,3}\s+\[?Unreleased\]?/i;
const RELEASE_HEADER_RE = /^#{2,3}\s+\[?v?(\d+\.\d+(?:\.\d+)?(?:-[a-zA-Z0-9.]+)?\]?)(?:[ \t]*(?:-|–|—|\()[ \t]*(\d{4}-\d{2}-\d{2}))?/i;
const BULLET_RE = /^\s*[-*+]\s+(.+)$/;

function parseAdrStatus(text: string): AdrStatus {
  const lower = text.toLowerCase();
  if (lower.includes('red') || lower.includes('reject')) return 'REJECTED';
  if (lower.includes('öneri') || lower.includes('propos') || lower.includes('taslak') || lower.includes('draft') || lower.includes('değerlendir')) return 'PROPOSED';
  if (lower.includes('eski') || lower.includes('supersed') || lower.includes('geçersiz')) return 'SUPERSEDED';
  if (lower.includes('deprecat')) return 'DEPRECATED';
  return 'ACCEPTED';
}

/**
 * KNOWLEDGE.md dosyasını ayrıştırıp ADR kartlarını ve kör noktaları (gotchas) çıkarır.
 */
export function parseKnowledgeMarkdown(content: string): { adrs: AdrItem[]; gotchas: GotchaItem[] } {
  const adrs: AdrItem[] = [];
  const gotchas: GotchaItem[] = [];

  if (typeof content !== 'string' || content.trim().length === 0) {
    return { adrs, gotchas };
  }

  const lines = content.replace(/^﻿/, '').split(/\r?\n/);
  let currentAdr: Partial<AdrItem> | null = null;
  let inGotchasSection = false;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // Bölüm başlık kontrolü (Gotchas / Kör Noktalar)
    if (/^#{2,3}\s+.*(?:kör nokta|gotcha|lesson|dersler|yasaklar)/i.test(trimmed)) {
      inGotchasSection = true;
      if (currentAdr && currentAdr.id && currentAdr.title) {
        adrs.push(currentAdr as AdrItem);
        currentAdr = null;
      }
      continue;
    } else if (trimmed.startsWith('## ') && inGotchasSection) {
      inGotchasSection = false;
    }

    // Gotcha tespiti 1: - [!] ...
    const gotchaMatch = GOTCHA_LINE_RE.exec(rawLine);
    if (gotchaMatch) {
      gotchas.push({ text: gotchaMatch[1].trim(), line: i + 1 });
      continue;
    }

    // Gotcha tespiti 2: > [!WARNING] veya Kör Noktalar bölümündeki maddeler
    const calloutMatch = CALLOUT_WARNING_RE.exec(rawLine);
    if (calloutMatch) {
      const nextLine = (i + 1 < lines.length && lines[i + 1].startsWith('>')) ? lines[i + 1].replace(/^>\s*/, '').trim() : '';
      const gText = calloutMatch[1] ? `${calloutMatch[1]} ${nextLine}`.trim() : (nextLine || 'Dikkat gerektiren kör nokta');
      gotchas.push({ text: gText, line: i + 1 });
      continue;
    }

    if (inGotchasSection) {
      const bMatch = BULLET_RE.exec(rawLine);
      if (bMatch && !trimmed.startsWith('- [ ]') && !trimmed.startsWith('- [x]')) {
        gotchas.push({ text: bMatch[1].trim(), line: i + 1 });
        continue;
      }
    }

    // ADR başlık tespiti: ### ADR-001: Başlık
    const adrMatch = ADR_HEADER_RE.exec(trimmed);
    if (adrMatch) {
      if (currentAdr && currentAdr.id && currentAdr.title) {
        adrs.push(currentAdr as AdrItem);
      }
      const rawId = adrMatch[1].toUpperCase().replace(/[_ ]/g, '-');
      const title = adrMatch[2].replace(/\*\*/g, '').trim();
      currentAdr = {
        id: rawId,
        title,
        status: 'ACCEPTED',
        line: i + 1,
        context: '',
        decision: '',
        consequences: ''
      };
      continue;
    }

    // ADR gövde alanları (Durum, Karar, Bağlam)
    if (currentAdr) {
      if (trimmed.startsWith('## ') || trimmed.startsWith('# ')) {
        // Yeni ana başlık geldi, ADR bitti
        adrs.push(currentAdr as AdrItem);
        currentAdr = null;
        continue;
      }

      if (/^(?:[-*+]\s+)?\*{0,2}(?:Durum|Status)[:*]/i.test(trimmed)) {
        const statusVal = trimmed.replace(/^(?:[-*+]\s+)?\*{0,2}(?:Durum|Status)[:*]\s*/i, '').replace(/\*/g, '').trim();
        currentAdr.status = parseAdrStatus(statusVal);
        currentAdr.statusLabel = statusVal;
      } else if (/^(?:[-*+]\s+)?\*{0,2}(?:Karar|Decision)[:*]/i.test(trimmed)) {
        currentAdr.decision = trimmed.replace(/^(?:[-*+]\s+)?\*{0,2}(?:Karar|Decision)[:*]\s*/i, '').replace(/\*/g, '').trim();
      } else if (/^(?:[-*+]\s+)?\*{0,2}(?:Bağlam|Context|Gerekçe)[:*]/i.test(trimmed)) {
        currentAdr.context = trimmed.replace(/^(?:[-*+]\s+)?\*{0,2}(?:Bağlam|Context|Gerekçe)[:*]\s*/i, '').replace(/\*/g, '').trim();
      } else if (/^(?:[-*+]\s+)?\*{0,2}(?:Sonuçlar|Consequences)[:*]/i.test(trimmed)) {
        currentAdr.consequences = trimmed.replace(/^(?:[-*+]\s+)?\*{0,2}(?:Sonuçlar|Consequences)[:*]\s*/i, '').replace(/\*/g, '').trim();
      } else if (trimmed && !currentAdr.decision && !trimmed.startsWith('#')) {
        // Karar satırı etiketsiz ilk paragrafta geçiyorsa doldur
        if (!currentAdr.context) {
          currentAdr.context = trimmed;
        }
      }
    }
  }

  if (currentAdr && currentAdr.id && currentAdr.title) {
    adrs.push(currentAdr as AdrItem);
  }

  return { adrs, gotchas };
}

/**
 * CHANGELOG.md dosyasını ayrıştırıp [Unreleased] bekleyen değişiklikleri ve son sürümü çıkarır.
 */
export function parseChangelogMarkdown(content: string): {
  unreleased: string[];
  latestRelease?: ChangelogRelease;
  totalReleases: number;
} {
  const unreleased: string[] = [];
  let latestRelease: ChangelogRelease | undefined = undefined;
  let totalReleases = 0;

  if (typeof content !== 'string' || content.trim().length === 0) {
    return { unreleased, totalReleases: 0 };
  }

  const lines = content.replace(/^﻿/, '').split(/\r?\n/);
  let inUnreleased = false;
  let currentRelease: ChangelogRelease | null = null;

  for (let i = 0; i < lines.length; i++) {
    const rawLine = lines[i];
    const trimmed = rawLine.trim();

    // 1. [Unreleased] başlığı
    if (UNRELEASED_HEADER_RE.test(trimmed)) {
      inUnreleased = true;
      continue;
    }

    // 2. Sürüm başlığı: ## [1.4.12] - 2026-10-15
    const releaseMatch = RELEASE_HEADER_RE.exec(trimmed);
    if (releaseMatch && !trimmed.toLowerCase().includes('unreleased')) {
      inUnreleased = false;
      totalReleases++;

      const version = releaseMatch[1].replace(/[[\]]/g, '').trim();
      const date = releaseMatch[2] || '';

      if (!latestRelease) {
        currentRelease = {
          version,
          date,
          changes: [],
          line: i + 1
        };
        latestRelease = currentRelease;
      } else {
        currentRelease = null; // Sadece son sürümün maddelerini topluyoruz
      }
      continue;
    }

    // Unreleased maddelerini topla
    if (inUnreleased) {
      const bMatch = BULLET_RE.exec(rawLine);
      if (bMatch) {
        const item = bMatch[1].trim();
        if (item && !item.startsWith('---')) {
          unreleased.push(item);
        }
      }
    } else if (currentRelease) {
      // Son yayınlanan sürüm maddelerini topla (en fazla 6 madde)
      const bMatch = BULLET_RE.exec(rawLine);
      if (bMatch && currentRelease.changes.length < 6) {
        currentRelease.changes.push(bMatch[1].trim());
      }
    }
  }

  return { unreleased, latestRelease, totalReleases };
}

/**
 * Çalışma alanı ve sistem dizinlerinde KNOWLEDGE.md ve CHANGELOG.md dosyalarını bulur.
 */
export function discoverKnowledgeFiles(options: {
  workspaceRoot?: string;
  homeDir?: string;
}): { knowledgePath?: string; changelogPath?: string } {
  const root = options.workspaceRoot || '';
  const home = options.homeDir || os.homedir();
  let knowledgePath: string | undefined = undefined;
  let changelogPath: string | undefined = undefined;

  if (root) {
    for (const rel of KNOWLEDGE_CANDIDATE_PATHS) {
      const candidate = path.join(root, ...rel.split('/'));
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        knowledgePath = candidate;
        break;
      }
    }
    for (const rel of CHANGELOG_CANDIDATE_PATHS) {
      const candidate = path.join(root, ...rel.split('/'));
      if (fs.existsSync(candidate) && fs.statSync(candidate).isFile()) {
        changelogPath = candidate;
        break;
      }
    }
  }

  // Fallback: Global plugin veya varsayılan dizinler
  if (!knowledgePath) {
    const globalCandidate = path.join(home, '.gemini', 'config', 'plugins', 'gravityguard', 'KNOWLEDGE.md');
    if (fs.existsSync(globalCandidate)) {
      knowledgePath = globalCandidate;
    }
  }

  return { knowledgePath, changelogPath };
}

/**
 * Knowledge Hub verilerini toplar.
 */
export function collectMemoryHubData(options: {
  workspaceRoot?: string;
  homeDir?: string;
}): MemoryHubData {
  const { knowledgePath, changelogPath } = discoverKnowledgeFiles(options);
  let knowledge: KnowledgeFile | undefined = undefined;
  let changelog: ChangelogFile | undefined = undefined;

  if (knowledgePath && fs.existsSync(knowledgePath)) {
    try {
      const content = fs.readFileSync(knowledgePath, 'utf8');
      const { adrs, gotchas } = parseKnowledgeMarkdown(content);
      knowledge = {
        path: knowledgePath,
        adrs,
        gotchas,
        totalAdrs: adrs.length,
        totalGotchas: gotchas.length
      };
    } catch (e) {
      console.debug('[GravityGuard] KNOWLEDGE.md read failed:', e);
    }
  }

  if (changelogPath && fs.existsSync(changelogPath)) {
    try {
      const content = fs.readFileSync(changelogPath, 'utf8');
      const { unreleased, latestRelease, totalReleases } = parseChangelogMarkdown(content);
      changelog = {
        path: changelogPath,
        unreleased,
        latestRelease,
        totalReleases
      };
    } catch (e) {
      console.debug('[GravityGuard] CHANGELOG.md read failed:', e);
    }
  }

  return { knowledge, changelog };
}

/**
 * KNOWLEDGE.md dosyasına yeni bir Mimari Karar (ADR) ekler.
 */
export function addAdrItem(
  filePath: string,
  adr: { id?: string; title: string; decision: string; status?: AdrStatus; context?: string }
): boolean {
  if (!filePath || !adr.title || !adr.decision) {
    return false;
  }
  try {
    let content = fs.existsSync(filePath) ? fs.readFileSync(filePath, 'utf8') : '# KNOWLEDGE.md — Mimari Hafıza ve Kararlar\n\n';
    
    // Otomatik sonraki ID'yi hesapla
    let nextNum = 1;
    const existingMatches = content.match(/ADR-(\d+)/gi);
    if (existingMatches) {
      for (const m of existingMatches) {
        const num = parseInt(m.replace(/ADR-/i, ''), 10);
        if (num >= nextNum) nextNum = num + 1;
      }
    }
    const adrId = adr.id || `ADR-${String(nextNum).padStart(3, '0')}`;
    const status = adr.status || 'ACCEPTED';
    const context = adr.context || 'Geliştirme oturumu sırasında kararlaştırıldı.';

    const newBlock = `
### ${adrId}: ${adr.title}
- **Durum:** ${status === 'ACCEPTED' ? 'Kabul Edildi' : status}
- **Tarih:** ${new Date().toISOString().split('T')[0]}
- **Bağlam:** ${context}
- **Karar:** ${adr.decision}
`;

    // Dosyaya ekle
    fs.mkdirSync(path.dirname(filePath), { recursive: true });
    fs.writeFileSync(filePath, content.trimEnd() + '\n' + newBlock, 'utf8');
    return true;
  } catch (err) {
    console.error('[GravityGuard] Failed to add ADR:', err);
    return false;
  }
}

/**
 * CHANGELOG.md dosyasına [Unreleased] başlığı altına yeni bir madde ekler.
 */
export function addChangelogItem(filePath: string, changeText: string): boolean {
  if (!filePath || !changeText.trim()) {
    return false;
  }
  try {
    const rawChange = changeText.trim();
    const formattedItem = rawChange.startsWith('-') ? rawChange : `- ${rawChange}`;
    
    if (!fs.existsSync(filePath)) {
      const initialContent = `# Changelog\n\n## [Unreleased]\n${formattedItem}\n`;
      fs.mkdirSync(path.dirname(filePath), { recursive: true });
      fs.writeFileSync(filePath, initialContent, 'utf8');
      return true;
    }

    const content = fs.readFileSync(filePath, 'utf8');
    const lines = content.split(/\r?\n/);
    let unreleasedIdx = -1;

    for (let i = 0; i < lines.length; i++) {
      if (UNRELEASED_HEADER_RE.test(lines[i].trim())) {
        unreleasedIdx = i;
        break;
      }
    }

    if (unreleasedIdx !== -1) {
      // [Unreleased] başlığının hemen altına ekle
      lines.splice(unreleasedIdx + 1, 0, formattedItem);
      fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
      return true;
    } else {
      // [Unreleased] başlığı yoksa, dosya başlığından sonra ekle
      const firstHeadingIdx = lines.findIndex(l => l.startsWith('# '));
      const insertIdx = firstHeadingIdx !== -1 ? firstHeadingIdx + 1 : 0;
      lines.splice(insertIdx, 0, '\n## [Unreleased]', formattedItem);
      fs.writeFileSync(filePath, lines.join('\n'), 'utf8');
      return true;
    }
  } catch (err) {
    console.error('[GravityGuard] Failed to add Changelog item:', err);
    return false;
  }
}
