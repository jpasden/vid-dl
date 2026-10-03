// Exercise the page's state machine without a network connection or downloads.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const vm = require('node:vm');
const html = fs.readFileSync(require('node:path').join(__dirname, '../index.html'), 'utf8');
const elements = new Map();
function element(id) {
  if (!elements.has(id)) {
    const classes = new Set();
    elements.set(id, {value: '', textContent: '', style: {}, dataset: {},
      disabled: false, checked: true, hidden: true, listeners: {}, attrs: {},
      addEventListener(event, fn) { this.listeners[event] = fn; },
      setAttribute(key, value) { this.attrs[key] = value; },
      classList: {add: (...names) => names.forEach(n => classes.add(n)),
        remove: (...names) => names.forEach(n => classes.delete(n)),
        contains: n => classes.has(n), toggle: () => {}}});
  }
  return elements.get(id);
}
let now = 100000, posts = 0, postResponse;
let status = {status: 'running', percent: 40, title: '<A & B> 中文'};
let nextPoll, tick;
const context = vm.createContext({
  document: {getElementById: element, querySelectorAll: () => []},
  Date: {now: () => now},
  setTimeout: fn => { nextPoll = fn; return 1; }, clearTimeout: () => {},
  setInterval: fn => { tick = fn; return 1; }, clearInterval: () => { tick = null; },
  fetch: async (url) => {
    if (url === '/api/info') return {json: async () => ({})};
    if (url === '/api/download') {
      posts++;
      return new Promise(resolve => { postResponse = () => resolve({ok: true, json: async () => ({id: 'job'})}); });
    }
    return {ok: true, json: async () => status};
  }
});
vm.runInContext(html.match(/<script>([\s\S]*?)<\/script>/)[1], context);
const run = code => vm.runInContext(code, context);
const flush = () => new Promise(resolve => setImmediate(resolve));
(async () => {
  element('url').value = 'https://example.test/one';
  run('updateButton()');
  assert.equal(element('goBtn').disabled, false);
  const started = run('startDownload()');
  run('startDownload()');
  element('url').listeners.keydown({key: 'Enter', preventDefault() {}});
  assert.equal(posts, 1, 'double clicks and Enter must not enqueue duplicate downloads');
  assert.equal(element('goBtn').disabled, true);
  assert.equal(element('videoTitle').textContent, 'Fetching video title…');
  postResponse(); await started; await flush();
  assert.equal(element('videoTitle').textContent, '<A & B> 中文');
  assert.equal(element('progressInner').style.width, '40%');
  status = {status: 'running', percent: 2};
  await nextPoll();
  assert.equal(element('progressInner').style.width, '40%');
  status = {status: 'done', percent: 100, completed_at: 98};
  await nextPoll();
  assert.equal(element('goBtn').disabled, true);
  assert.equal(element('goBtn').textContent, 'Completed · 0:02 ago');
  now += 63000; tick();
  assert.equal(element('goBtn').textContent, 'Completed · 1:05 ago');
  run('startDownload()'); assert.equal(posts, 1);
  element('url').value = 'https://example.test/two';
  element('url').listeners.input();
  assert.equal(element('goBtn').disabled, false);
  const second = run('startDownload()');
  assert.equal(element('progressInner').style.width, '0%');
  status = {status: 'error', percent: 0, error: 'Test failure'};
  postResponse(); await second; await flush();
  assert.equal(element('goBtn').disabled, true);
  assert.match(element('goBtn').textContent, /change URL/);
  assert.equal(tick, null);
  console.log('PASS: duplicate prevention, title, monotonic progress, timer, URL changes, error locking');
})().catch(err => {console.error(err); process.exitCode = 1;});
