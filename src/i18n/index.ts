// Zero-dependency pure TypeScript translation registry
// Full i18next-style dictionary with parameter interpolation support

import { tr } from './tr';
import { en } from './en';

export const resources = {
  tr,
  en
};

let currentLang: 'tr' | 'en' = 'tr';

export function initI18n(initialLang: string = 'tr'): { language: string } {
  currentLang = initialLang.toLowerCase().startsWith('tr') ? 'tr' : 'en';
  return { language: currentLang };
}

export function setLanguage(lang: 'tr' | 'en'): void {
  currentLang = lang;
}

export function getCurrentLanguage(): 'tr' | 'en' {
  return currentLang;
}

function interpolate(text: string, options?: Record<string, unknown>): string {
  if (!options) return text;
  let res = text;
  for (const [k, v] of Object.entries(options)) {
    res = res.replace(new RegExp(`\\{\\{${k}\\}\\}|\\{${k}\\}`, 'g'), String(v));
  }
  return res;
}

export function t(key: string, options?: Record<string, unknown>): string {
  const parts = key.split('.');
  let cur: any = resources[currentLang]?.translation;
  for (const p of parts) {
    if (cur && typeof cur === 'object' && p in cur) {
      cur = cur[p];
    } else {
      cur = undefined;
      break;
    }
  }
  if (typeof cur === 'string') {
    return interpolate(cur, options);
  }
  // Fallback to English
  let fallback: any = resources.en.translation;
  for (const p of parts) {
    if (fallback && typeof fallback === 'object' && p in fallback) {
      fallback = fallback[p];
    } else {
      fallback = undefined;
      break;
    }
  }
  if (typeof fallback === 'string') {
    return interpolate(fallback, options);
  }
  return key;
}
