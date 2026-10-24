import * as vscode from 'vscode';
import { initI18n, t, setLanguage, getCurrentLanguage } from './i18n';
import { probeRouter, initializeRouterSecrets } from './router_client';
import { handleEnhancePrompt, handleFindSkills, handleOpenConfig } from './commands';
import { GuardianViewProvider } from './webview/provider';

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  await initializeRouterSecrets(context);
  const savedLang = context.globalState.get<string>('gravityguard.language');
  const initialLang = savedLang || 'tr';
  initI18n(initialLang);
  console.log(`[GravityGuard] Extension activated successfully! Language: ${initialLang}`);

  // 1. Register Status Bar Item for Prompt Enhancement
  const promptStatusBarItem = vscode.window.createStatusBarItem(
    vscode.StatusBarAlignment.Right,
    100
  );
  promptStatusBarItem.command = 'antigravityBridge.enhancePrompt';
  promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
  promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
  promptStatusBarItem.show();
  context.subscriptions.push(promptStatusBarItem);

  // 2. Register Webview Provider for GravityGuard Live Monitor
  const provider = new GuardianViewProvider(
    context.extensionUri,
    context,
    () => {
      promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
      promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
    }
  );
  context.subscriptions.push(
    { dispose: () => provider.dispose() },
    vscode.window.registerWebviewViewProvider('antigravity-guardian-view', provider, {
      webviewOptions: { retainContextWhenHidden: true }
    })
  );

  // 3. Register Commands
  context.subscriptions.push(
    vscode.commands.registerCommand('antigravityBridge.ping', async () => {
      const health = await probeRouter();
      if (health.ok) {
        vscode.window.showInformationMessage(t('actions.pingLive', { detail: health.detail }));
      } else {
        vscode.window.showWarningMessage(t('actions.pingWarning', { detail: health.detail }));
      }
    }),
    vscode.commands.registerCommand('antigravityBridge.refreshLogs', () => {
      provider.updateHtml();
    }),
    vscode.commands.registerCommand('antigravityBridge.resetWebview', () => {
      provider.resetWebview();
    }),
    vscode.commands.registerCommand('antigravityBridge.clearLogs', () => {
      provider.clearLogs();
    }),
    vscode.commands.registerCommand('antigravityBridge.toggleLanguage', async () => {
      const next = getCurrentLanguage() === 'tr' ? 'en' : 'tr';
      setLanguage(next);
      await context.globalState.update('gravityguard.language', next);
      promptStatusBarItem.text = `$(sparkle) ${t('actions.enhancePrompt')}`;
      promptStatusBarItem.tooltip = t('actions.statusBarTooltip');
      provider.updateHtml();
      vscode.window.showInformationMessage(t('actions.langSwitched', { lang: next.toUpperCase() }));
    }),
    vscode.commands.registerCommand('antigravityBridge.openConfig', async () => {
      await handleOpenConfig();
    }),
    vscode.commands.registerCommand('antigravityBridge.enhancePrompt', async () => {
      await handleEnhancePrompt();
    }),
    vscode.commands.registerCommand('antigravityBridge.findSkills', async () => {
      await handleFindSkills();
    })
  );
}

export function deactivate(): void {}
