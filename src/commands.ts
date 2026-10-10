import * as vscode from 'vscode';
import * as fs from 'fs';
import * as os from 'os';
import * as path from 'path';
import { classifyIntent, modeLabel, shouldAskForMode, IntentClassification, IntentMode } from './intent';
import { t } from './i18n';
import { requestPromptEnhancement, EnhancementResult } from './router_client';

export async function handleFindSkills(): Promise<void> {
  let workspaceRoot = '';
  if (vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders.length > 0) {
    workspaceRoot = vscode.workspace.workspaceFolders[0].uri.fsPath;
  }
  const findSkillScript = path.join(os.homedir(), '.gemini', 'config', 'skills', 'find-skill', 'scripts', 'find_skill.ts');
  if (fs.existsSync(findSkillScript)) {
    const term = vscode.window.createTerminal({ name: 'GravityGuard: Find Skills' });
    term.show();
    const targetDir = workspaceRoot ? `"${workspaceRoot}"` : `"${process.cwd()}"`;
    term.sendText(`node --experimental-strip-types "${findSkillScript}" ${targetDir}`);
  } else {
    vscode.window.showInformationMessage('find-skill script not found at ~/.gemini/config/skills/find-skill');
  }
}

export async function handleOpenConfig(): Promise<void> {
  const workspaceFolders = vscode.workspace.workspaceFolders;
  let cfgFile = '';
  if (workspaceFolders && workspaceFolders.length > 0) {
    cfgFile = path.join(workspaceFolders[0].uri.fsPath, '.gravityguard.json');
  } else {
    cfgFile = path.join(os.homedir(), '.gravityguard.json');
    vscode.window.showInformationMessage(t('actions.configNoWorkspaceNotice'));
  }

  try {
    if (!fs.existsSync(cfgFile)) {
      fs.writeFileSync(cfgFile, JSON.stringify({
        "governance": { "enforceDocObligations": true },
        "complexity": { "singleWriteLoc": 200, "totalLoc": 500 },
        "guards": {
          "G0_SECRET_LEAK": "block",
          "G1_SILENT_EXCEPTION": "block",
          "G2_TEST_INTEGRITY": "block",
          "G3_COMPILER_BYPASS": "warn",
          "G4_IMPORT_MATRIX": "block",
          "T1_TEST_EVIDENCE": "warn"
        }
      }, null, 2), 'utf8');
    }
    const doc = await vscode.workspace.openTextDocument(cfgFile);
    await vscode.window.showTextDocument(doc, { viewColumn: vscode.ViewColumn.One, preview: false });
  } catch (e: any) {
    vscode.window.showErrorMessage(t('actions.configOpenError', { error: e.message }));
  }
}

export async function handleEnhancePrompt(): Promise<void> {
  const editor = vscode.window.activeTextEditor;
  let initialText = '';

  if (editor && !editor.selection.isEmpty) {
    initialText = editor.document.getText(editor.selection).trim();
  }

  const inputPrompt = await vscode.window.showInputBox({
    prompt: t('actions.promptInputTitle'),
    placeHolder: t('actions.promptInputPlaceholder'),
    value: initialText,
    ignoreFocusOut: true
  });

  if (!inputPrompt || inputPrompt.trim() === '') {
    return;
  }

  const classification = classifyIntent(inputPrompt.trim());
  const mode = await resolveMode(classification);

  try {
    let result: EnhancementResult | undefined;
    await vscode.window.withProgress(
      {
        location: vscode.ProgressLocation.Notification,
        title: t('actions.promptPreparing', { mode: modeLabel(mode) }),
        cancellable: false
      },
      async () => {
        result = await requestPromptEnhancement(inputPrompt.trim(), mode);
      }
    );

    if (!result || !result.text) {
      vscode.window.showErrorMessage(t('actions.promptFailed'));
      return;
    }

    const enhancedResult = result.text;

    // 1. Copy directly to clipboard
    await vscode.env.clipboard.writeText(enhancedResult);

    // 2. If editor has selected text, optionally replace it
    if (editor && !editor.selection.isEmpty) {
      await editor.edit(editBuilder => {
        editBuilder.replace(editor.selection, enhancedResult);
      });
    }

    // 3. Inform user with action button
    const originNote = result.offline ? t('actions.promptOfflineNote') : '';
    const action = await vscode.window.showInformationMessage(
      t('actions.promptSuccess', { mode: modeLabel(result.mode), note: originNote }),
      t('actions.openInNewDoc')
    );

    if (action === t('actions.openInNewDoc')) {
      const doc = await vscode.workspace.openTextDocument({
        content: enhancedResult,
        language: 'markdown'
      });
      await vscode.window.showTextDocument(doc);
    }
  } catch (error: any) {
    console.error('[Prompt Enhancer Error]:', error);
    vscode.window.showErrorMessage(
      t('actions.promptError', { error: error?.message || error })
    );
  }
}

export async function resolveMode(classification: IntentClassification): Promise<IntentMode> {
  if (!shouldAskForMode(classification)) {
    return classification.mode;
  }

  const MODES: IntentMode[] = ['consult', 'implement', 'audit'];
  const pick = await vscode.window.showQuickPick(
    [
      {
        label: t('actions.modeAuto', { mode: modeLabel(classification.mode) }),
        description: t('actions.modeAutoDesc'),
        mode: classification.mode
      },
      ...MODES.filter(mode => mode !== classification.mode).map(mode => ({
        label: modeLabel(mode),
        description: mode === 'consult'
          ? t('actions.modeConsultDesc')
          : mode === 'implement'
            ? t('actions.modeImplementDesc')
            : t('actions.modeAuditDesc'),
        mode
      }))
    ],
    { placeHolder: t('actions.modePlaceholder') }
  );

  return pick ? pick.mode : classification.mode;
}
