const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const deferred = () => { let resolve, reject; const promise = new Promise((yes, no) => { resolve = yes; reject = no; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 25; i++) await Promise.resolve(); };
const outcome = (promise) => promise.then((value) => ({ value }), (error) => ({ error }));
const user = (id = '1', role = 'administration') => ({ id, login: `synthetic-${id}`, fullName: 'Synthetic Person', phoneNumber: 'test', plotNumber: '', isAdmin: true, staffRole: role });
function load(file, modules, fetchMock) {
  const js = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
  }).outputText;
  const exports = {};
  new Function('require', 'exports', 'fetch', js)((name) => { assert.ok(name in modules, name); return modules[name]; }, exports, fetchMock);
  return exports;
}
function fixture(options = {}) {
  let token = options.token === undefined ? 'synthetic-token-1' : options.token;
  let state;
  const requests = [], resets = [];
  const tokens = {
    getAccessToken: () => token,
    restoreAccessToken: async () => token,
    setAccessToken: async (value) => { token = value; },
  };
  const http = load('services/api/httpClient.ts', {
    'react-native': { Platform: { OS: 'android' } }, '@/services/api/config': { API_BASE_URL: 'https://example.test' }, '@/services/api/tokenStore': tokens,
  }, async (url, args) => {
    const pending = deferred();
    requests.push({ url, args, respond: (status, body) => pending.resolve({ status, ok: status >= 200 && status < 300, json: async () => body }), reject: pending.reject });
    return pending.promise;
  });
  const api = load('services/api/apiAuthService.ts', {
    '@/services/api/httpClient': http, '@/services/api/tokenStore': tokens,
    '@/services/newsNotifications': { unregisterNewsNotifications: options.unregister || (async () => {}) },
  }).apiAuthService;
  const store = load('store/authStore.ts', {
    zustand: { create: (init) => {
      const set = (value) => { state = { ...state, ...(typeof value === 'function' ? value(state) : value) }; };
      const get = () => state; state = init(set, get);
      return Object.assign((selector) => selector(state), { setState: set, getState: get });
    } },
    '@/services/authService': { mockAuthService: api }, '@/services/api/httpClient': http,
    '@/store/passesStore': { usePassesStore: { getState: () => ({ resetPasses: (id) => resets.push(id) }) } },
  }).useAuthStore;
  store.setState({ user: options.user === undefined ? user() : options.user, restoreState: 'success' });
  return { api, http, store, requests, resets, getToken: () => token, setToken: (value) => { token = value; } };
}
function tokenFixture(blockWrites = false) {
  let persisted = 'synthetic-old-token';
  const reads = [], writes = [];
  const change = async (value) => {
    const pending = deferred(); writes.push({ value, ...pending });
    if (blockWrites) await pending.promise;
    persisted = value;
  };
  const tokens = load('services/api/tokenStore.ts', {
    'react-native': { Platform: { OS: 'android' } },
    '@react-native-async-storage/async-storage': { default: {
      getItem: () => { const pending = deferred(); reads.push(pending); return pending.promise; },
      setItem: (_, value) => change(value), removeItem: () => change(null),
    } },
  });
  return { tokens, reads, writes, persisted: () => persisted };
}
let checks = 0;
async function scenario(name, run) { await run(); checks++; console.log(`PASS ${name}`); }
async function main() {
  await scenario('same-user demotion wins over an older administration response in service and store', async () => {
    const f = fixture();
    const old = f.store.getState().validateSession(); await flush();
    const latest = f.store.getState().validateSession(); await flush();
    f.requests[1].respond(200, user('1', 'dispatcher')); await latest;
    f.requests[0].respond(200, user()); await old;
    assert.equal(f.store.getState().user.staffRole, 'dispatcher');
    assert.equal((await f.api.getCurrentUser()).staffRole, 'dispatcher');
    assert.equal(f.requests.length, 2);
  });
  await scenario('late user response cannot restore a signed-out session', async () => {
    const f = fixture();
    const old = f.store.getState().validateSession(); await flush();
    await f.store.getState().logout();
    assert.equal(f.store.getState().user, null);
    f.requests[0].respond(200, user()); await old;
    assert.equal(f.store.getState().user, null); assert.equal(f.getToken(), null);
    assert.equal(await f.api.getCurrentUser(), null);
  });
  await scenario('switching accounts discards the prior account response and cached user', async () => {
    const f = fixture();
    const old = f.store.getState().validateSession(); await flush();
    const login = f.store.getState().login('synthetic-2', 'synthetic-password'); await flush();
    f.requests[1].respond(200, { success: true, access_token: 'synthetic-token-2', user: user('2', 'dispatcher') }); assert.equal(await login, true);
    f.requests[0].respond(200, user()); await old;
    assert.equal(f.store.getState().user.id, '2'); assert.equal(f.getToken(), 'synthetic-token-2');
    assert.equal((await f.api.getCurrentUser()).id, '2');
    assert.equal(f.resets.at(-1), '2');
  });
  await scenario('late old-token 401 cannot clear the new login or trigger logout', async () => {
    const f = fixture();
    const old = outcome(f.http.apiRequest('/api/news')); await flush();
    const login = f.store.getState().login('synthetic-2', 'synthetic-password'); await flush();
    f.requests[1].respond(200, { success: true, access_token: 'synthetic-token-2', user: user('2', 'dispatcher') }); await login;
    f.requests[0].respond(401, { detail: 'Old token expired' }); assert.ok((await old).error);
    assert.equal(f.getToken(), 'synthetic-token-2'); assert.equal(f.store.getState().user.id, '2');
  });
  await scenario('current-token 401 still clears session and pass state', async () => {
    const f = fixture();
    const result = outcome(f.http.apiRequest('/api/news')); await flush(); f.requests[0].respond(401, { detail: 'Token expired' });
    assert.ok((await result).error); assert.equal(f.getToken(), null); assert.equal(f.store.getState().user, null); assert.equal(f.resets.at(-1), null);
  });
  await scenario('latest login wins when two login responses arrive out of order', async () => {
    const f = fixture({ token: null, user: null });
    const old = f.store.getState().login('synthetic-1', 'synthetic-password'); await flush();
    const next = f.store.getState().login('synthetic-2', 'synthetic-password'); await flush();
    f.requests[1].respond(200, { success: true, access_token: 'synthetic-token-2', user: user('2', 'dispatcher') }); assert.equal(await next, true);
    f.requests[0].respond(200, { success: true, access_token: 'synthetic-token-1', user: user() }); assert.equal(await old, false);
    assert.equal(f.store.getState().user.id, '2'); assert.equal(f.store.getState().error, null); assert.equal(f.getToken(), 'synthetic-token-2');
  });
  await scenario('late logout notification revocation cannot clear a later login', async () => {
    const revoke = deferred(); const f = fixture({ unregister: () => revoke.promise });
    const logout = f.store.getState().logout();
    assert.equal(f.store.getState().user, null);
    const login = f.store.getState().login('synthetic-2', 'synthetic-password'); await flush();
    f.requests[0].respond(200, { success: true, access_token: 'synthetic-token-2', user: user('2', 'dispatcher') }); await login;
    revoke.resolve(); await logout;
    assert.equal(f.getToken(), 'synthetic-token-2'); assert.equal(f.store.getState().user.id, '2'); assert.equal(f.store.getState().logoutState, 'idle');
    const validate = f.store.getState().validateSession(); await flush();
    assert.equal(f.requests.length, 2, 'validation must not remain disabled after superseding logout');
    f.requests[1].respond(200, user('2', 'dispatcher')); await validate;
  });
  await scenario('failed new login during logout cannot revive the prior token', async () => {
    const revoke = deferred(); const f = fixture({ unregister: () => revoke.promise });
    const logout = f.store.getState().logout();
    const login = f.store.getState().login('synthetic-2', 'wrong-synthetic-password'); await flush();
    f.requests[0].respond(401, { detail: 'Invalid credentials' }); assert.equal(await login, false);
    revoke.resolve(); await logout;
    assert.equal(f.getToken(), null); assert.equal(f.store.getState().user, null);
  });
  await scenario('late restore cannot replace a new authenticated account or leave startup loading', async () => {
    const f = fixture({ user: null });
    const restore = f.store.getState().restoreSession(); await flush();
    const login = f.store.getState().login('synthetic-2', 'synthetic-password'); await flush();
    f.requests[1].respond(200, { success: true, access_token: 'synthetic-token-2', user: user('2', 'dispatcher') }); await login;
    f.requests[0].respond(200, user()); await restore;
    assert.equal(f.store.getState().user.id, '2'); assert.equal(f.store.getState().restoreState, 'success');
  });
  await scenario('transient validation failure preserves the current restricted role', async () => {
    const f = fixture({ user: user('1', 'dispatcher') });
    const validate = f.store.getState().validateSession(); await flush(); f.requests[0].reject(Error('Network unavailable')); await validate;
    assert.equal(f.store.getState().user.staffRole, 'dispatcher'); assert.equal(f.getToken(), 'synthetic-token-1');
  });
  await scenario('late native token restore cannot undo logout', async () => {
    const f = tokenFixture(); const restore = f.tokens.restoreAccessToken(); await flush();
    await f.tokens.setAccessToken(null);
    f.reads[0].resolve('synthetic-old-token');
    assert.equal(await restore, null); assert.equal(f.tokens.getAccessToken(), null); assert.equal(f.persisted(), null);
  });
  await scenario('late native token restore cannot replace a new login token', async () => {
    const f = tokenFixture(); const restore = f.tokens.restoreAccessToken(); await flush();
    await f.tokens.setAccessToken('synthetic-new-token');
    f.reads[0].resolve('synthetic-old-token');
    assert.equal(await restore, 'synthetic-new-token'); assert.equal(f.tokens.getAccessToken(), 'synthetic-new-token'); assert.equal(f.persisted(), 'synthetic-new-token');
  });
  await scenario('native persistence writes serialize so an older login cannot overwrite the new one on disk', async () => {
    const f = tokenFixture(true);
    const old = f.tokens.setAccessToken('synthetic-old-login'); await flush();
    const next = f.tokens.setAccessToken('synthetic-new-login'); await flush();
    assert.equal(f.tokens.getAccessToken(), 'synthetic-new-login'); assert.equal(f.writes.length, 1);
    f.writes[0].resolve(); await old; await flush(); assert.equal(f.writes.length, 2);
    f.writes[1].resolve(); await next;
    assert.equal(f.persisted(), 'synthetic-new-login');
  });
  await scenario('restore waits for a pending logout removal before reading native storage', async () => {
    const f = tokenFixture(true);
    const logout = f.tokens.setAccessToken(null); await flush();
    const restore = f.tokens.restoreAccessToken(); await flush(); assert.equal(f.reads.length, 0);
    f.writes[0].resolve(); await logout; await flush();
    assert.equal(f.persisted(), null); f.reads[0].resolve(f.persisted()); assert.equal(await restore, null);
  });
  await scenario('an obsolete restore cannot clear the new coalesced restore promise', async () => {
    const f = tokenFixture(); const old = f.tokens.restoreAccessToken(); await flush();
    await f.tokens.setAccessToken(null);
    const newer = f.tokens.restoreAccessToken(); await flush();
    f.reads[0].resolve('synthetic-old-token'); await old;
    const coalesced = f.tokens.restoreAccessToken(); await flush(); assert.equal(f.reads.length, 2);
    f.reads[1].resolve(null); assert.equal(await newer, null); assert.equal(await coalesced, null);
  });
  console.log(`PASS ${checks} session race scenarios using actual transpiled HTTP/service/store and synthetic transport.`);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
