import * as fs from 'fs';
import * as path from 'path';
import * as os from 'os';

export type SkillScope = 'workspace' | 'global' | 'plugin' | 'builtin';

export type AgentType = 'claude' | 'cursor' | 'gemini' | 'copilot' | 'windsurf' | 'generic';

export interface SkillItem {
  id: string;
  name: string;
  description: string;
  scope: SkillScope;
  skillFilePath: string;
  skillDirPath: string;
  agentType?: AgentType;
}

export function parseSkillMdContent(content: string, fallbackName: string): { name: string; description: string } {
  let name = fallbackName;
  let description = '';

  const fmMatch = content.match(/^---\r?\n([\s\S]*?)\r?\n---/);
  if (fmMatch) {
    const yaml = fmMatch[1];
    const nameMatch = yaml.match(/^name:\s*(.+)$/m);
    if (nameMatch) {
      name = nameMatch[1].trim().replace(/^['"]|['"]$/g, '');
    }
    const descMatch = yaml.match(/^description:\s*(.+)$/m);
    if (descMatch) {
      description = descMatch[1].trim().replace(/^['"]|['"]$/g, '');
    }
  }

  if (!description) {
    const cleaned = content.replace(/^---\r?\n[\s\S]*?\r?\n---/, '');
    const lines = cleaned.split(/\r?\n/);
    for (const line of lines) {
      const trimmed = line.trim();
      if (trimmed && !trimmed.startsWith('#') && !trimmed.startsWith('---') && !trimmed.startsWith('!')) {
        description = trimmed;
        break;
      }
    }
  }

  if (!description) {
    description = 'No description provided.';
  }

  return { name, description };
}

export function scanDirectoryForSkills(dirPath: string, scope: SkillScope, agentType: AgentType = 'generic'): SkillItem[] {
  const items: SkillItem[] = [];
  if (!fs.existsSync(dirPath)) {
    return items;
  }

  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    for (const entry of entries) {
      if (entry.isDirectory()) {
        const skillDir = path.join(dirPath, entry.name);
        const skillFile = path.join(skillDir, 'SKILL.md');
        if (fs.existsSync(skillFile)) {
          try {
            const content = fs.readFileSync(skillFile, 'utf8');
            const meta = parseSkillMdContent(content, entry.name);
            items.push({
              id: `${scope}:${entry.name}`,
              name: meta.name || entry.name,
              description: meta.description,
              scope,
              skillFilePath: skillFile,
              skillDirPath: skillDir,
              agentType
            });
          } catch (readErr) {
            console.warn(`[GravityGuard] Failed to read skill at ${skillFile}:`, readErr);
          }
        }
      }
    }
  } catch (dirErr) {
    console.warn(`[GravityGuard] Failed to scan skills directory at ${dirPath}:`, dirErr);
  }

  return items;
}

function firstHeading(content: string): string | undefined {
  const body = content.replace(/^---\r?\n[\s\S]*?\r?\n---/, '');
  const m = body.match(/^#{1,6}\s+(.+?)\s*#*\s*$/m);
  return m ? m[1].trim() : undefined;
}

/** Reads a single agent rule/instruction file (CLAUDE.md, .cursorrules, ...). Returns null if missing/unreadable. */
export function readAgentFile(filePath: string, scope: SkillScope, agentType: AgentType): SkillItem | null {
  try {
    if (!fs.statSync(filePath).isFile()) {
      return null;
    }
    const content = fs.readFileSync(filePath, 'utf8');
    const baseName = path.basename(filePath);
    const meta = parseSkillMdContent(content, baseName);
    let name = meta.name;
    if (name === baseName) {
      name = firstHeading(content) || baseName;
    }
    return {
      id: `${scope}:${agentType}:${filePath}`,
      name,
      description: meta.description,
      scope,
      skillFilePath: filePath,
      skillDirPath: path.dirname(filePath),
      agentType
    };
  } catch {
    return null;
  }
}

/** Reads all *.md / *.mdc rule files directly inside a directory (non-recursive). */
function scanRuleFilesInDir(dirPath: string, scope: SkillScope, agentType: AgentType): SkillItem[] {
  const items: SkillItem[] = [];
  try {
    const entries = fs.readdirSync(dirPath, { withFileTypes: true });
    entries.sort((a, b) => a.name.localeCompare(b.name));
    for (const entry of entries) {
      if (entry.isFile() && /\.(mdc|md)$/i.test(entry.name)) {
        const item = readAgentFile(path.join(dirPath, entry.name), scope, agentType);
        if (item) {
          items.push(item);
        }
      }
    }
  } catch {
    // directory missing: skip silently
  }
  return items;
}

export function scanAllSkills(workspaceRoot?: string): SkillItem[] {
  const all: SkillItem[] = [];
  const seenPaths = new Set<string>();

  const addItems = (items: SkillItem[]) => {
    for (const item of items) {
      const normalized = path.normalize(item.skillFilePath).toLowerCase();
      if (!seenPaths.has(normalized)) {
        seenPaths.add(normalized);
        all.push(item);
      }
    }
  };

  // 1. Workspace Skills
  if (workspaceRoot) {
    addItems(scanDirectoryForSkills(path.join(workspaceRoot, '.agent', 'skills'), 'workspace', 'gemini'));
    addItems(scanDirectoryForSkills(path.join(workspaceRoot, '.gemini', 'skills'), 'workspace', 'gemini'));
    addItems(scanDirectoryForSkills(path.join(workspaceRoot, 'skills'), 'workspace', 'generic'));

    // Universal agent rule / instruction files
    const addFile = (rel: string[], agent: AgentType) => {
      const item = readAgentFile(path.join(workspaceRoot, ...rel), 'workspace', agent);
      if (item) {
        addItems([item]);
      }
    };
    addFile(['CLAUDE.md'], 'claude');
    addFile(['CLAUDE.local.md'], 'claude');
    addFile(['.claude', 'CLAUDE.md'], 'claude');
    addItems(scanDirectoryForSkills(path.join(workspaceRoot, '.claude', 'skills'), 'workspace', 'claude'));
    addFile(['GEMINI.md'], 'gemini');
    addFile(['AGENTS.md'], 'gemini');
    addFile(['docs', 'AGENTS.md'], 'gemini');
    addFile(['.cursorrules'], 'cursor');
    addItems(scanRuleFilesInDir(path.join(workspaceRoot, '.cursor', 'rules'), 'workspace', 'cursor'));
    addItems(scanDirectoryForSkills(path.join(workspaceRoot, '.cursor', 'skills'), 'workspace', 'cursor'));
    addFile(['.github', 'copilot-instructions.md'], 'copilot');
    addFile(['.windsurfrules'], 'windsurf');
  }

  // 2. Global Skills (~/.gemini/config/skills)
  const home = os.homedir();
  addItems(scanDirectoryForSkills(path.join(home, '.gemini', 'config', 'skills'), 'global', 'gemini'));
  addItems(scanDirectoryForSkills(path.join(home, '.agent', 'skills'), 'global', 'gemini'));
  addItems(scanDirectoryForSkills(path.join(home, '.claude', 'skills'), 'global', 'claude'));

  // 3. Plugin Skills (~/.gemini/config/plugins/*/skills)
  const pluginsDir = path.join(home, '.gemini', 'config', 'plugins');
  if (fs.existsSync(pluginsDir)) {
    try {
      const pluginEntries = fs.readdirSync(pluginsDir, { withFileTypes: true });
      for (const pe of pluginEntries) {
        if (pe.isDirectory()) {
          const pSkillDir = path.join(pluginsDir, pe.name, 'skills');
          addItems(scanDirectoryForSkills(pSkillDir, 'plugin', 'gemini'));
        }
      }
    } catch (pluginErr) {
      console.warn('[GravityGuard] Failed to scan plugin skills directory:', pluginErr);
    }
  }

  // 4. Built-in Skills (~/.gemini/antigravity/builtin/skills)
  const builtinDir = path.join(home, '.gemini', 'antigravity', 'builtin', 'skills');
  addItems(scanDirectoryForSkills(builtinDir, 'builtin', 'gemini'));

  return all;
}
