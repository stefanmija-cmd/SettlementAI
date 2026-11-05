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

test('sender posts stable results, heartbeat and corrections; stop prevents sends', () => {
  const vm = require('node:vm');
  const source = require('node:fs').readFileSync(require.resolve('../tools/flashscore-watch.js'), 'utf8');
  let now = Date.now(), tick, homeScore = '1';
  const sent = [];
  const row = { id: 'g_1_test', querySelector: selector => ({ textContent: {
    '.event__participant--home': 'Home', '.event__participant--away': 'Away',
    '.event__score--home': homeScore, '.event__score--away': '0'
  }[selector] }) };
  const browser = {
    URL, Date: class extends Date { constructor(...args) { super(...(args.length ? args : [now])); } static now() { return now; } },
    location: { hostname: 'www.flashscore.com', pathname: '/football/' },
    localStorage: { getItem: () => null, setItem() {} },
    document: { body: {}, hidden: false, querySelectorAll: () => [row], querySelector: () => row },
    MutationObserver: class { observe() {} disconnect() {} },
    setTimeout: () => 1, clearTimeout() {}, setInterval: fn => { tick = fn; return 2; }, clearInterval() {},
    console: { info() {}, warn() {}, error() {}, table() {} }, structuredClone,
    GM_xmlhttpRequest: options => { sent.push(options); options.onload({ status: 200 }); return { abort() {} }; }
  };
  browser.window = browser;
  vm.createContext(browser);
  vm.runInContext(source, browser);
  browser.flashscoreWatcher.connect('https://receiver.example', 'test-token-with-at-least-24-characters');
  assert.equal(sent.length, 0);
  now += 1000; tick();
  assert.equal(sent.length, 1);
  assert.equal(sent[0].url, 'https://receiver.example/snapshot');
  assert.equal(JSON.parse(sent[0].data).matches[0].homeScore, '1');
  assert.ok(!JSON.stringify(browser.flashscoreWatcher.status()).includes('test-token'));
  now += 3000; tick();
  assert.equal(sent.length, 1);
  now += 15000; tick();
  assert.equal(sent.length, 2);
  homeScore = '0'; tick();
  now += 3000; tick();
  assert.equal(sent.length, 3);
  assert.equal(JSON.parse(sent[2].data).matches[0].homeScore, '0');
  browser.flashscoreWatcher.stop();
  now += 20000; tick();
  assert.equal(sent.length, 3);
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
