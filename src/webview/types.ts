import type { TaskFile } from '../tasks';

export interface LogEvent {
  status?: string;
  timestamp?: string;
  target?: string;
  action?: string;
  reason?: string;
  ruleId?: string;
  outcome?: string;
  resolvedRuleId?: string;
  recoveryAttempts?: number;
  resolutionMs?: number;
  agent?: string;
  conversationId?: string;
  [key: string]: any;
}

export interface GuardianData {
  activeGuard?: string;
  status?: string;
  lastCheck?: string;
  events?: LogEvent[];
}

/**
 * Shared view model assembled once per render and consumed by every tab renderer.
 */
export interface GuardianViewModel {
  data: GuardianData; // parsed live log (srp_guardian_live.json) or the default
  eventsList: LogEvent[]; // filterEventsAfterSeq(data.events || [], clearedAfterSeq)
  workspaceRoot: string;
  projectName: string;
  govData: any;
  pendingTests: Record<string, any>;
  pendingDocs: Record<string, any>;
  resolutionIntents: any[];
  stopRetries: number;
  sessionId: string;
  projectCfg: any;
  totalObligations: number;
  tasks: TaskFile[]; // checkbox task files discovered for the project roots / active conversation
  defaultTaskPath?: string; // fallback path to create/append tasks when no file exists or for quick-add
}
