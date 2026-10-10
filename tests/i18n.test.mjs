import test from 'node:test';
import assert from 'node:assert/strict';
import { initI18n, setLanguage, getCurrentLanguage, t, resources } from '../dist/i18n/index.js';

test('i18n initialization defaults to tr or en correctly', () => {
  initI18n('tr');
  assert.equal(getCurrentLanguage(), 'tr');
  assert.equal(t('tabs.events'), 'Olaylar');
  assert.equal(t('stats.blocked'), 'Engellendi');
  assert.equal(t('actions.refresh'), 'Yenile');
  assert.equal(t('actions.clear'), 'Temizle');
});

test('i18n switches language to en dynamically', () => {
  setLanguage('en');
  assert.equal(getCurrentLanguage(), 'en');
  assert.equal(t('tabs.events'), 'Events');
  assert.equal(t('stats.blocked'), 'Blocked');
  assert.equal(t('actions.refresh'), 'Refresh');
  assert.equal(t('actions.clear'), 'Clear');
});

test('i18n restores language to tr', () => {
  setLanguage('tr');
  assert.equal(getCurrentLanguage(), 'tr');
  assert.equal(t('tabs.obligations'), 'Yükümlülükler');
  assert.equal(t('stats.approved'), 'Onaylandı');
});

test('i18n parameter interpolation works for {{var}} and {var}', () => {
  setLanguage('tr');
  assert.equal(
    t('insights.medianAttempts', { attempts: 2 }),
    'Medyan: 2 deneme'
  );
  setLanguage('en');
  assert.equal(
    t('insights.medianAttempts', { attempts: 2 }),
    'Median: 2 attempts'
  );
});

test('all essential keys exist in both tr and en translation dictionaries', () => {
  const trKeys = Object.keys(resources.tr.translation);
  const enKeys = Object.keys(resources.en.translation);
  assert.deepEqual(trKeys.sort(), enKeys.sort(), 'Top-level translation keys must match in both languages');

  for (const group of ['tabs', 'current', 'live', 'insights', 'stats', 'actions', 'obligations', 'rules', 'events', 'skills']) {
    const trGroupKeys = Object.keys(resources.tr.translation[group] || {});
    const enGroupKeys = Object.keys(resources.en.translation[group] || {});
    assert.deepEqual(
      trGroupKeys.sort(),
      enGroupKeys.sort(),
      `Sub-group keys for '${group}' must match between TR and EN`
    );
  }
});
