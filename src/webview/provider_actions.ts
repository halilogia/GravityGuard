import * as vscode from 'vscode';
import { t } from '../i18n';
import { HookProposalCache, runHookControl, splitHookFile } from './hook_proposals';
import type { ApprovalView } from './approval_tickets';

/** A new blocked action: a notification with the two buttons, so the user need not open the panel. */
export function announceApprovalTicket(
  ticket: ApprovalView,
  onDecide: (action: 'allow' | 'deny', id: string) => Promise<void>
): void {
  const allow = t('hooks.allowOnce');
  const deny = t('hooks.reject');
  const what = ticket.action?.command || ticket.action?.target || '';
  void Promise.resolve(
    vscode.window.showWarningMessage(
      t('hooks.approvalPrompt', { rule: ticket.rule, what: what.slice(0, 120) }),
      allow,
      deny
    )
  ).then(choice => {
    if (choice === allow) return onDecide('allow', ticket.id);
    if (choice === deny) return onDecide('deny', ticket.id);
    return undefined;
  });
}

/** One click, no modal: the button is the user's decision. The trusted engine command records it. */
export async function executeApprovalDecision(
  approvalScript: string,
  action: 'allow' | 'deny',
  id: string
): Promise<void> {
  try {
    const answer = await runHookControl(approvalScript, { action, id });
    if (!answer?.ok) throw new Error(answer?.error || 'unknown error');
    vscode.window.showInformationMessage(t(action === 'allow' ? 'hooks.approvalAllowed' : 'hooks.approvalDenied'));
  } catch (error: any) {
    vscode.window.showErrorMessage(t('hooks.failed', { error: error?.message || String(error) }));
  }
}

/** User clicked Approve / Reject / Revert: confirm in a modal, then run the trusted engine command. */
export async function executeHookProposalAction(
  hookScript: string,
  hookCache: HookProposalCache,
  roots: string[],
  command: string,
  file: string,
  sha?: string
): Promise<boolean> {
  const where = splitHookFile(file);
  if (!where) return false;
  const data = hookCache.current(roots);
  const pending = data.pending.find(view => view.id === where.id && view.root === where.root);
  const installed = data.installed.find(receipt => receipt.id === where.id && receipt.root === where.root);
  const action = command === 'approveHookProposal' ? 'approve' : command === 'rejectHookProposal' ? 'reject' : 'revert';
  if (action !== 'reject') {
    const targetFile = action === 'approve' ? pending?.target_file : installed?.target_file;
    const yes = t('hooks.confirmButton');
    const choice = await vscode.window.showWarningMessage(
      t(action === 'approve' ? 'hooks.confirmApprove' : 'hooks.confirmRevert', { id: where.id, file: targetFile || '?' }),
      { modal: true, detail: action === 'approve' ? pending?.diff : undefined },
      yes
    );
    if (choice !== yes) return false;
  }
  try {
    const answer = await runHookControl(hookScript, { action, roots, root: where.root, id: where.id, sha256: sha || '' });
    if (!answer?.ok) throw new Error(answer?.error || 'unknown error');
    const notice = action === 'approve'
      ? t('hooks.installed', { file: answer.target_file })
      : action === 'reject'
        ? t('hooks.rejected', { id: where.id })
        : t('hooks.reverted', { id: where.id });
    vscode.window.showInformationMessage(notice);
  } catch (error: any) {
    vscode.window.showErrorMessage(t('hooks.failed', { error: error?.message || String(error) }));
  }
  return true;
}
