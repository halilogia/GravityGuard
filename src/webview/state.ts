import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { filterEventsAfterSeq } from '../view_filter';
import { TaskFile, collectTasks, resolveDefaultTaskFilePath } from '../tasks';
import { MemoryHubData, collectMemoryHubData } from '../knowledge';
import { GuardianData, GuardianViewModel } from './types';

/**
 * Absolute path of the live guardian log written by the SRP guardian.
 * The central log (~/.gemini/logs) wins; a workspace-local log is only a fallback when the central one is absent.
 */
export function getLiveLogPath(): string {
  const centralPath = path.join(os.homedir(), '.gemini', 'logs', 'srp_guardian_live.json');
  if (fs.existsSync(centralPath)) {
    return centralPath;
  }
  const folders = vscode.workspace.workspaceFolders;
  if (folders && folders.length > 0) {
    const localPath = path.join(folders[0].uri.fsPath, '.gravityguard', 'logs', 'srp_guardian_live.json');
    if (fs.existsSync(localPath)) {
      return localPath;
    }
  }
  return centralPath;
}

/**
 * Gathers all data required to render the Guardian webview:
 * live log, workspace info, governance state and project/user config.
 */
export function loadGuardianState(clearedAfterSeq: number | null): GuardianViewModel {
  const logPath = getLiveLogPath();
  let data: GuardianData = { activeGuard: 'GravityGuard', status: 'ONLINE', events: [] };

  if (fs.existsSync(logPath)) {
    try {
      data = JSON.parse(fs.readFileSync(logPath, 'utf8'));
    } catch (e) {
      console.warn('Failed to parse live log file:', e);
    }
  }

  // Resolve workspace folder and read governance / project config
  let workspaceRoot = '';
  let projectName = 'Workspace';
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
    projectName = path.basename(workspaceRoot);
  }

  let govData: any = null;
  let pendingTests: Record<string, any> = {};
  let pendingDocs: Record<string, any> = {};
  let resolutionIntents: any[] = [];
  let stopRetries = 0;
  let sessionId = 'active';

  let govPath = workspaceRoot ? path.join(workspaceRoot, '.gravityguard', 'runtime', 'governance.json') : '';

  // No workspace folder open: auto-discover the project root from recent event targets
  if (!workspaceRoot) {
    const recentEvents: any[] = Array.isArray(data.events) ? data.events : [];
    discovery:
    for (let i = recentEvents.length - 1; i >= 0; i--) {
      const target = recentEvents[i]?.target;
      if (typeof target !== 'string' || !path.isAbsolute(target)) {
        continue;
      }
      let curr = target;
      for (let depth = 0; depth < 6; depth++) {
        const govCandidate = path.join(curr, '.gravityguard', 'runtime', 'governance.json');
        const cfgCandidate = path.join(curr, '.gravityguard.json');
        if (fs.existsSync(govCandidate) || fs.existsSync(cfgCandidate)) {
          workspaceRoot = curr;
          projectName = path.basename(curr);
          if (fs.existsSync(govCandidate)) {
            govPath = govCandidate;
          }
          break discovery;
        }
        const parent = path.dirname(curr);
        if (parent === curr) {
          break;
        }
        curr = parent;
      }
    }
  }

  if (!govPath || !fs.existsSync(govPath)) {
    const pluginGovPath = path.join(os.homedir(), '.gemini', 'config', 'plugins', 'gravityguard', '.gravityguard', 'runtime', 'governance.json');
    if (fs.existsSync(pluginGovPath)) {
      govPath = pluginGovPath;
    } else {
      const homeGovPath = path.join(os.homedir(), '.gravityguard', 'runtime', 'governance.json');
      if (fs.existsSync(homeGovPath)) {
        govPath = homeGovPath;
      }
    }
  }

  if (govPath && fs.existsSync(govPath)) {
    try {
      govData = JSON.parse(fs.readFileSync(govPath, 'utf8'));
      pendingTests = govData.test_obligations?.pending || {};
      pendingDocs = govData.doc_obligations?.pending || {};
      resolutionIntents = govData.resolution_intents || [];
      stopRetries = govData.stop_retries || 0;
      if (govData.sessions && Object.keys(govData.sessions).length > 0) {
        sessionId = Object.keys(govData.sessions)[0];
      }
    } catch (e) {
      console.warn('Failed to parse governance state:', e);
    }
  }

  let projectCfg: any = null;
  if (workspaceRoot) {
    const cfgPath = path.join(workspaceRoot, '.gravityguard.json');
    if (fs.existsSync(cfgPath)) {
      try {
        projectCfg = JSON.parse(fs.readFileSync(cfgPath, 'utf8'));
      } catch (e) {
        console.warn('Failed to parse .gravityguard.json:', e);
      }
    }
  }
  if (!projectCfg) {
    const userCfgPath = path.join(os.homedir(), '.gravityguard.json');
    if (fs.existsSync(userCfgPath)) {
      try {
        projectCfg = JSON.parse(fs.readFileSync(userCfgPath, 'utf8'));
      } catch (e) {
        console.warn('Failed to parse user .gravityguard.json:', e);
      }
    }
  }

  const totalObligations = Object.keys(pendingTests).length + Object.keys(pendingDocs).length;
  let eventsList = filterEventsAfterSeq(data.events || [], clearedAfterSeq);

  // Task checklists: markdown task files of the project roots / active Antigravity brain folder
  // plus governance.json tasks (read errors are swallowed inside collectTasks)
  let tasks: TaskFile[] = [];
  const activeEditorPath = vscode.window.activeTextEditor?.document.fileName;
  const normalizedSessionId = sessionId === 'active' ? null : sessionId;
  const defaultTaskPath = resolveDefaultTaskFilePath(workspaceRoot, normalizedSessionId);

  try {
    tasks = collectTasks({
      workspaceRoot,
      obligationMaps: [pendingTests, pendingDocs],
      govData,
      events: Array.isArray(data.events) ? data.events : [],
      // 'active' is only the placeholder used when governance has no recorded session
      sessionId: normalizedSessionId,
      activeEditorPath,
      allowBrainFallback: true
    });
  } catch (e) {
    console.debug('[GravityGuard] Task discovery failed:', e);
  }

  // Knowledge Hub: KNOWLEDGE.md (ADRs, Gotchas) and CHANGELOG.md (Unreleased, Latest Release)
  let memory: MemoryHubData = {};
  try {
    memory = collectMemoryHubData({ workspaceRoot });
  } catch (e) {
    console.debug('[GravityGuard] Memory hub discovery failed:', e);
  }

  return {
    data,
    eventsList,
    workspaceRoot,
    projectName,
    govData,
    pendingTests,
    pendingDocs,
    resolutionIntents,
    stopRetries,
    sessionId,
    projectCfg,
    totalObligations,
    tasks,
    defaultTaskPath,
    memory
  };
}
