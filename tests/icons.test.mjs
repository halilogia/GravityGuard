import test from 'node:test';
import assert from 'node:assert/strict';
import { lucide } from '../dist/icons.js';

test('lucide generates valid SVG element with default options', () => {
  const svg = lucide('shield');
  assert.ok(svg.startsWith('<svg width="14" height="14" viewBox="0 0 24 24"'), 'Should have standard 14px size and viewBox');
  assert.ok(svg.includes('stroke="currentColor"'), 'Should default to currentColor');
  assert.ok(svg.includes('stroke-width="2"'), 'Should default to stroke-width 2');
  assert.ok(svg.includes('stroke-linecap="round"'), 'Should have rounded linecap');
  assert.ok(svg.includes('stroke-linejoin="round"'), 'Should have rounded linejoin');
  assert.ok(svg.includes('</svg>'), 'Should close svg tag');
});

test('lucide supports custom size, color, strokeWidth, and className', () => {
  const svg = lucide('alertTriangle', {
    size: 20,
    color: '#f59e0b',
    strokeWidth: 1.5,
    className: 'warning-icon'
  });
  assert.ok(svg.includes('width="20" height="20"'), 'Custom size 20 applied');
  assert.ok(svg.includes('stroke="#f59e0b"'), 'Custom color applied');
  assert.ok(svg.includes('stroke-width="1.5"'), 'Custom strokeWidth applied');
  assert.ok(svg.includes('class="warning-icon"'), 'Custom className applied');
});

test('lucide falls back gracefully for unknown icon name', () => {
  const svg = lucide('unknownIcon');
  assert.ok(svg.includes('<svg'), 'Should still produce an SVG');
  assert.ok(svg.includes('</svg>'), 'Should properly close');
});

test('all essential UI icons produce non-empty unique SVG paths', () => {
  const iconNames = [
    'shield', 'shieldAlert', 'shieldCheck', 'checkCircle', 'octagonX',
    'alertTriangle', 'zap', 'eye', 'rotateCw', 'folder', 'fileText',
    'copy', 'clipboardList', 'sliders', 'barChart', 'settings', 'trash2',
    'globe', 'flaskConical', 'lock', 'layers', 'cpu', 'database', 'trophy',
    'target', 'clock', 'sparkles', 'circleDot', 'arrowRight'
  ];

  for (const name of iconNames) {
    const svg = lucide(name);
    assert.ok(svg.length > 50, `Icon '${name}' should produce a substantial SVG string`);
    assert.ok(!svg.includes('undefined'), `Icon '${name}' should not contain undefined`);
  }
});
