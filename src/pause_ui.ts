import * as vscode from 'vscode';
import { t } from './i18n';
import { DEFAULT_PAUSE_MINUTES, pauseFor, pauseStatus, remainingMinutes, resumeNow } from './pause_control';

export function registerPauseUi(context: vscode.ExtensionContext): { refresh: () => void } {
  const item = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Right, 99);
  item.command = 'gravityguard.togglePause';

  const refresh = (): void => {
    const st = pauseStatus();
    if (st) {
      item.text = `$(debug-pause) ${t('pause.paused', { min: remainingMinutes(st) })}`;
      item.tooltip = t('pause.resumeTooltip');
      item.backgroundColor = new vscode.ThemeColor('statusBarItem.warningBackground');
    } else {
      item.text = `$(shield) ${t('pause.active')}`;
      item.tooltip = t('pause.pauseTooltip', { min: DEFAULT_PAUSE_MINUTES });
      item.backgroundColor = undefined;
    }
  };

  const doPause = async (): Promise<void> => {
    const yes = t('pause.confirmYes');
    const pick = await vscode.window.showWarningMessage(
      t('pause.confirm', { min: DEFAULT_PAUSE_MINUTES }), { modal: true }, yes
    );
    if (pick !== yes) return;
    pauseFor(DEFAULT_PAUSE_MINUTES, 'extension');
    refresh();
  };
  const doResume = (): void => {
    resumeNow();
    refresh();
  };

  refresh();
  item.show();
  const timer = setInterval(refresh, 30000);
  context.subscriptions.push(
    item,
    { dispose: () => clearInterval(timer) },
    vscode.commands.registerCommand('gravityguard.pause', doPause),
    vscode.commands.registerCommand('gravityguard.resume', doResume),
    vscode.commands.registerCommand('gravityguard.togglePause', () => (pauseStatus() ? doResume() : doPause()))
  );
  return { refresh };
}
