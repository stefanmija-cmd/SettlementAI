const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createTracker, csv, readRow } = require('../tools/flashscore-watch.js');
const match = { id: 'g_1_abc', home: 'Home', away: 'Away', homeScore: '0', awayScore: '0' };

test('complete file starts in browser context without CommonJS and can restart', () => {
  const vm = require('node:vm');
  const fs = require('node:fs');
  const source = fs.readFileSync(require.resolve('../tools/flashscore-watch.js'), 'utf8');
  const storage = new Map();
  const browser = {
    location: { hostname: 'www.flashscore.com', pathname: '/football/' },
    localStorage: { getItem: k => storage.get(k) ?? null, setItem: (k, v) => storage.set(k, v) },
    document: { body: {}, hidden: false, querySelectorAll: () => [], querySelector: () => null },
    MutationObserver: class { observe() {} disconnect() {} },
    setTimeout: () => 1, clearTimeout() {}, setInterval: () => 2, clearInterval() {},
    console: { info() {}, warn() {}, error() {}, table() {} }, structuredClone
  };
  browser.window = browser;
  vm.createContext(browser);
  vm.runInContext(source, browser);
  assert.equal(browser.flashscoreWatcher.status().running, true);
  vm.runInContext(source, browser);
  assert.equal(browser.flashscoreWatcher.status().running, true);
  browser.flashscoreWatcher.stop();
  assert.equal(browser.flashscoreWatcher.status().running, false);
});

test('baseline, goal, unchanged result, correction and reload', () => {
  let tracker = createTracker();
  assert.equal(tracker.sample([match]).length, 0);
  const goal = { ...match, homeScore: '1' };
  assert.equal(tracker.sample([goal], '2026-11-05T17:00:00Z')[0].previousHomeScore, '0');
  assert.equal(tracker.sample([goal]).length, 0);
  tracker = createTracker(JSON.parse(JSON.stringify(tracker.state)));
  assert.equal(tracker.sample([goal]).length, 0);
  assert.equal(tracker.sample([match])[0].previousHomeScore, '1');
  assert.equal(tracker.state.changes.length, 2);
});

test('missing matches and newly loaded matches do not create goals', () => {
  const tracker = createTracker();
  tracker.sample([match]);
  tracker.sample([]);
  assert.equal(tracker.sample([match, { ...match, id: 'g_1_other', homeScore: '3' }]).length, 0);
  assert.equal(Object.keys(tracker.state.scores).length, 2);
});

test('DOM parsing skips missing cells, scheduled matches and nonnumeric scores', () => {
  const values = { '.event__participant--home': ' Home ', '.event__participant--away': 'Away',
    '.event__score--home': '0', '.event__score--away': '1' };
  const row = { id: match.id, querySelector: selector => values[selector] == null ? null : { textContent: values[selector] } };
  assert.deepEqual(readRow(row), { ...match, awayScore: '1' });
  values['.event__score--home'] = '-';
  assert.equal(readRow(row), null);
  delete values['.event__score--home'];
  assert.equal(readRow(row), null);
});

test('CSV preserves quotes and neutralizes spreadsheet formulas', () => {
  const output = csv([{ ...match, home: '=CMD()', away: 'A,"B"' }]);
  assert.ok(output.includes('"\'=CMD()"'));
  assert.ok(output.includes('"A,""B"""'));
  assert.ok(output.startsWith('\uFEFFobservedAt,'));
});
