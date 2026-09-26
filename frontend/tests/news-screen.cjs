const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Exercise the real screen's state, focus cleanup and rendered component props
// with controlled hooks/transport. This is not an Android renderer or tap test.
const source = fs.readFileSync(path.resolve(__dirname, '../src/screens/NewsScreen.tsx'), 'utf8');
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020,
    jsx: ts.JsxEmit.React, esModuleInterop: true,
  },
}).outputText;
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
};
const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
const same = (left, right) => left?.length === right.length && right.every((value, i) => Object.is(value, left[i]));

// Use the real typed HTTP error, and check that adding its status does not
// change Error compatibility, messages, network failures or 401 cleanup.
const httpSource = fs.readFileSync(path.resolve(__dirname, '../src/services/api/httpClient.ts'), 'utf8');
const httpCode = ts.transpileModule(httpSource, {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 },
}).outputText;
const httpState = { status: 200, body: {}, failure: null, token: 'test-token' };
const httpClient = {};
new Function('require', 'exports', 'fetch', httpCode)((name) => ({
  'react-native': { Platform: { OS: 'android' } },
  '@/services/api/config': { API_BASE_URL: 'https://example.test' },
  '@/services/api/tokenStore': {
    getAccessToken: () => httpState.token,
    setAccessToken: async (token) => { httpState.token = token; },
  },
})[name], httpClient, async () => {
  if (httpState.failure) throw httpState.failure;
  return {
    status: httpState.status,
    ok: httpState.status >= 200 && httpState.status < 300,
    json: async () => httpState.body,
  };
});
const { ApiError } = httpClient;

function fixture(initialTarget) {
  const slots = [], effects = [], requests = [];
  let cursor = 0, target = initialTarget, tree;
  const react = {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }),
    useState: (initial) => {
      const index = cursor++;
      if (!(index in slots)) slots[index] = initial;
      return [slots[index], (value) => { slots[index] = typeof value === 'function' ? value(slots[index]) : value; }];
    },
    useRef: (initial) => {
      const index = cursor++;
      if (!(index in slots)) slots[index] = { current: initial };
      return slots[index];
    },
    useCallback: (callback, deps) => {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) slots[index] = { callback, deps };
      return slots[index].callback;
    },
    useEffect: (effect, deps) => {
      const index = cursor++;
      if (!slots[index] || !same(slots[index].deps, deps)) {
        const previous = slots[index];
        slots[index] = { deps };
        effects.push(() => {
          previous?.cleanup?.();
          slots[index].cleanup = effect();
        });
      }
    },
  };
  const request = (postId) => {
    const pending = deferred();
    requests.push({ postId, ...pending });
    return pending.promise;
  };
  const navigation = { isFocused: () => true, navigate: () => {}, setParams: (params) => { target = params.postId; } };
  const modules = {
    react,
    'react-native': {
      ActivityIndicator: 'ActivityIndicator', Pressable: 'Pressable', RefreshControl: 'RefreshControl',
      ScrollView: 'ScrollView', Text: 'Text', View: 'View',
      AppState: { addEventListener: () => ({ remove() {} }) },
    },
    '@expo/vector-icons': { MaterialCommunityIcons: 'Icon' },
    '@react-navigation/native': { useFocusEffect: (effect) => react.useEffect(effect, [effect]) },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' },
    '@/components/AppBackground': { AppBackground: 'AppBackground' },
    '@/components/news/NewsPostCard': { NewsPostCard: 'NewsPostCard' },
    '@/components/news/NewsState': { NewsState: 'NewsState', newsStyles: {} },
    '@/components/news/ConfirmNewsDelete': { ConfirmNewsDelete: 'ConfirmNewsDelete' },
    '@/services/api/httpClient': httpClient,
    '@/services/newsService': {
      getNewsPost: request, getNews: () => request(undefined),
      newsError: (error) => error.message, deleteNews: async () => {},
    },
    '@/store/authStore': { useAuthStore: (selector) => selector({ user: { isAdmin: false } }) },
    '@/theme': { theme: { colors: {} } },
  };
  const exported = {};
  new Function('require', 'exports', compiled)((name) => {
    assert.ok(name in modules, `unexpected dependency ${name}`);
    return modules[name];
  }, exported);
  const render = (runEffects = true) => {
    cursor = 0;
    tree = exported.NewsScreen({ navigation, route: { params: { postId: target } } });
    if (runEffects) while (effects.length) effects.shift()();
    return tree;
  };
  const nodes = (type) => {
    const found = [];
    const visit = (node) => {
      if (!node || typeof node !== 'object') return;
      if (node.type === type) found.push(node);
      node.children?.forEach(visit);
    };
    visit(tree);
    return found;
  };
  return { requests, render, nodes, navigate: (postId) => { target = postId; }, navigation };
}

async function main() {
  const f = fixture(1);
  f.render();
  f.requests[0].resolve({ id: 1, text: 'Publication A' });
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard')[0].props.post.id, 1);

  // The previous card disappears even before focus effects start the next HTTP request.
  f.navigate(2);
  f.render(false);
  assert.equal(f.nodes('NewsPostCard').length, 0, 'A must not appear under target B');
  f.render();
  f.requests[1].reject(new ApiError('Новость не найдена', 404));
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard').length, 0, '404 must not leave an unrelated card');
  assert.equal(f.nodes('NewsState')[0].props.description, 'Новость не найдена');
  assert.equal(typeof f.nodes('NewsState')[0].props.onRetry, 'function');

  f.nodes('NewsState')[0].props.onRetry();
  f.requests[2].resolve({ id: 2, text: 'Publication B' });
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard')[0].props.post.id, 2, 'retry can recover the intended post');

  f.navigate(3);
  f.render();
  f.navigate(4);
  f.render();
  f.requests[4].resolve({ id: 4, text: 'Publication D' });
  await flush();
  f.requests[3].resolve({ id: 3, text: 'Late publication C' });
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard')[0].props.post.id, 4, 'late old success cannot overwrite the new target');

  f.navigate(5);
  f.render();
  f.navigate(6);
  f.render();
  f.requests[6].resolve({ id: 6, text: 'Publication F' });
  await flush();
  f.requests[5].reject(new Error('Late unavailable post E'));
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard')[0].props.post.id, 6, 'late old failure cannot erase the new target');
  assert.equal(f.nodes('NewsState').length, 0);

  f.navigate(undefined);
  f.render(false);
  assert.equal(f.nodes('NewsPostCard').length, 0, 'returning to latest does not retain the notification target');
  f.render();
  f.requests[7].resolve({ items: [{ id: 7, text: 'Newest publication' }] });
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard')[0].props.post.id, 7);

  const refresh = f.nodes('Pressable').find((node) => node.props.accessibilityLabel === 'Обновить новости');
  refresh.props.onPress();
  f.requests[8].reject(new ApiError('Новость не найдена', 404));
  await flush();
  f.render();
  assert.equal(f.nodes('NewsPostCard').length, 0, 'failed refresh clears the no-longer-available card');
  assert.equal(f.nodes('NewsState')[0].props.description, 'Новость не найдена');
  for (const reason of [new Error('Network unavailable'), new Error('Request timed out'), new ApiError('Server unavailable', 503)]) {
    const offline = fixture(10);
    offline.render();
    offline.requests[0].resolve({ id: 10, text: 'Already loaded' });
    await flush();
    offline.render();
    offline.nodes('Pressable').find((node) => node.props.accessibilityLabel === 'Обновить новости').props.onPress();
    offline.requests[1].reject(reason);
    await flush();
    offline.render();
    assert.equal(offline.nodes('NewsPostCard')[0].props.post.id, 10, 'transient refresh keeps the same target');
    assert.ok(offline.nodes('Text').some((node) => node.children.includes(reason.message)), 'refresh error remains visible');

    offline.navigate(11);
    offline.render(false);
    assert.equal(offline.nodes('NewsPostCard').length, 0, 'new target immediately hides the offline cached post');
    offline.render();
    offline.requests[2].reject(reason);
    await flush();
    offline.render();
    assert.equal(offline.nodes('NewsPostCard').length, 0, 'new target failure cannot show a different cached post');
    assert.equal(offline.nodes('NewsState')[0].props.description, reason.message);
  }
  {
    const forbidden = fixture(12);
    forbidden.render();
    forbidden.requests[0].resolve({ id: 12, text: 'Previously accessible' });
    await flush();
    forbidden.render();
    forbidden.nodes('Pressable').find((node) => node.props.accessibilityLabel === 'Обновить новости').props.onPress();
    forbidden.requests[1].reject(new ApiError('Access withdrawn', 403));
    await flush();
    forbidden.render();
    assert.equal(forbidden.nodes('NewsPostCard').length, 0, '403 clears a previously accessible same-target post');
    assert.equal(forbidden.nodes('NewsState')[0].props.description, 'Access withdrawn');
  }
  let unauthorized = 0;
  httpClient.setUnauthorizedHandler(() => { unauthorized += 1; });
  for (const status of [403, 404, 503, 401]) {
    httpState.status = status;
    httpState.body = { detail: `HTTP failure ${status}` };
    await assert.rejects(httpClient.apiRequest('/api/news/1'), (reason) => {
      assert.ok(reason instanceof Error);
      assert.ok(reason instanceof ApiError);
      assert.equal(reason.status, status);
      assert.equal(reason.message, `HTTP failure ${status}`);
      return true;
    });
  }
  assert.equal(httpState.token, null);
  assert.equal(unauthorized, 1, 'typed errors retain the existing unauthorized cleanup');
  httpState.failure = new Error('Transport failed');
  await assert.rejects(httpClient.apiRequest('/api/news/1'), (reason) => reason === httpState.failure);
  console.log('PASS 14 news screen scenarios: target isolation, 403/404 clearing, retry, stale responses, transient refresh preservation; 5 HTTP error contract checks.');
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
