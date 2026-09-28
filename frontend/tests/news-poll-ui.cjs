const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

// Controlled React hooks exercise real component handlers and their async races.
// This is not a DOM/native renderer; visual and touch QA is separate.
const deferred = () => { let resolve, reject; const promise = new Promise((a, b) => { resolve = a; reject = b; }); return { promise, resolve, reject }; };
const flush = async () => { for (let i = 0; i < 20; i++) await Promise.resolve(); };
const same = (a, b) => a?.length === b.length && b.every((value, i) => Object.is(value, a[i]));
function load(file, modules) {
  const compiled = ts.transpileModule(fs.readFileSync(path.resolve(__dirname, '../src', file), 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React, esModuleInterop: true },
  }).outputText;
  const exported = {};
  new Function('require', 'exports', 'setTimeout', 'clearTimeout', compiled)((name) => {
    assert.ok(name in modules, `unexpected dependency ${name}`); return modules[name];
  }, exported, () => 1, () => {});
  return exported;
}
function fixture(file, name, initialProps, extras = {}) {
  const slots = [], effects = [];
  let cursor = 0, tree, props = initialProps;
  const react = {
    createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat(Infinity) }),
    memo: (component) => component,
    useState: (initial) => { const i = cursor++; if (!(i in slots)) slots[i] = typeof initial === 'function' ? initial() : initial; return [slots[i], (value) => { slots[i] = typeof value === 'function' ? value(slots[i]) : value; }]; },
    useRef: (initial) => { const i = cursor++; if (!(i in slots)) slots[i] = { current: initial }; return slots[i]; },
    useCallback: (callback, deps) => { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) slots[i] = { callback, deps }; return slots[i].callback; },
    useEffect: (effect, deps) => { const i = cursor++; if (!slots[i] || !same(slots[i].deps, deps)) { const old = slots[i]; slots[i] = { deps }; effects.push(() => { old?.cleanup?.(); slots[i].cleanup = effect(); }); } },
  };
  const rn = Object.fromEntries(['ActivityIndicator', 'Text', 'View', 'Pressable', 'Image', 'TextInput', 'ScrollView', 'KeyboardAvoidingView', 'FlatList', 'Modal'].map((key) => [key, key]));
  Object.assign(rn, { Platform: { OS: 'web' }, StyleSheet: { create: (styles) => styles, absoluteFillObject: {} }, AppState: { addEventListener: () => ({ remove() {} }) }, useWindowDimensions: () => ({ width: 390, height: 844 }), Linking: {} });
  const modules = {
    react, 'react-native': rn, '@expo/vector-icons': { MaterialCommunityIcons: 'Icon' },
    '@react-navigation/native': { useIsFocused: () => true },
    'react-native-safe-area-context': { SafeAreaView: 'SafeAreaView' },
    'expo-av': { Video: 'Video', ResizeMode: { CONTAIN: 'contain' } }, 'expo-file-system': {}, 'expo-sharing': {},
    'expo-document-picker': {}, 'expo-image-picker': {},
    '@/components/news/newsDownload': {}, '@/theme': { theme: { colors: {} } },
    '@/components/news/NewsPollCard': { NewsPollCard: 'NewsPollCard' },
    '@/components/news/NewsPollEditor': { NewsPollEditor: 'NewsPollEditor' },
    '@/components/AppBackground': { AppBackground: 'AppBackground' }, '@/components/ScreenHeader': { ScreenHeader: 'ScreenHeader' },
    '@/components/news/NewsState': { NewsState: 'NewsState', newsStyles: {} },
    '@/utils/roles': { canManageNews: (user) => !!user?.isAdmin && user.staffRole !== 'dispatcher' },
    ...extras,
  };
  const component = load(file, modules)[name];
  const render = () => { cursor = 0; tree = component(props); while (effects.length) effects.shift()(); return tree; };
  const nodes = (type) => {
    const found = [];
    const visit = (node) => { if (!node || typeof node !== 'object' || (node.type === 'Modal' && !node.props.visible)) return; if (node.type === type) found.push(node); node.children?.forEach(visit); };
    visit(tree); return found;
  };
  const content = (node) => typeof node === 'string' || typeof node === 'number' ? String(node) : node?.children?.map(content).join('') || '';
  const button = (text) => nodes('Pressable').find((node) => content(node) === text);
  return { render, nodes, button, content, setProps: (next) => { props = { ...props, ...next }; }, unmount: () => { slots.forEach((slot) => slot?.cleanup?.()); } };
}
const basePoll = () => ({ id: 2, question: 'Где провести собрание?', options: [{ id: 5, text: 'В клубе', votes: 0 }, { id: 6, text: 'У въезда', votes: 0 }], total_votes: 0, my_option_id: null, is_closed: false, closed_at: null, can_edit: true });
function pollFixture(poll = basePoll(), admin = false) {
  const requests = [], changes = [];
  const request = (kind, args) => { const pending = deferred(); requests.push({ kind, args, ...pending }); return pending.promise; };
  let f;
  f = fixture('components/news/NewsPollCard.tsx', 'NewsPollCard', { postId: 17, poll, admin, onChange: (next) => { changes.push(next); if (next) f.setProps({ poll: next }); } }, {
    '@/services/newsService': { voteNewsPoll: (...args) => request('vote', args), closeNewsPoll: (...args) => request('close', args), getNewsPost: (...args) => request('refresh', args), newsError: (error) => error.message },
  });
  f.render(); f.render(); return { ...f, requests, changes };
}
const helpers = load('services/newsService.ts', {
  'react-native': { Platform: { OS: 'web' } }, '@react-native-async-storage/async-storage': {},
  '@/services/api/config': { API_BASE_URL: 'https://example.test' }, '@/services/api/httpClient': {}, '@/services/api/tokenStore': {},
});
function editorFixture({ post, draft, user = { id: 1, isAdmin: true, staffRole: 'administration' } } = {}) {
  const updates = [], publications = [], saves = [], navigation = [];
  const pending = deferred();
  const f = fixture('screens/NewsEditorScreen.tsx', 'NewsEditorScreen', {
    route: { params: { postId: post?.id } },
    navigation: { addListener: () => () => {}, goBack() {}, navigate: (...args) => navigation.push(args), dispatch() {} },
  }, {
    '@/store/authStore': { useAuthStore: (selector) => selector({ user }) },
    '@/services/newsService': { ...helpers,
      getNewsPost: async () => post, loadNewsDraft: async () => draft || null,
      saveNewsDraft: async (id, value) => saves.push(value), clearNewsDraft: async () => {},
      updateNews: (...args) => { updates.push(args); return pending.promise; },
      publishNews: (...args) => { publications.push(args); return pending.promise; },
    },
  });
  return { ...f, pending, updates, publications, saves, navigation };
}
let count = 0;
async function scenario(name, run) { await run(); count++; console.log(`PASS ${name}`); }
async function main() {
  await scenario('selection is required and a double tap sends one vote with no optimistic count', async () => {
    const f = pollFixture();
    assert.equal(f.button('Проголосовать').props.disabled, true);
    f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio')[1].props.onPress(); f.render();
    const submit = f.button('Проголосовать').props.onPress; submit(); submit();
    assert.equal(f.requests.length, 1); assert.deepEqual(f.requests[0].args, [17, 6]); assert.equal(f.changes.length, 0);
    f.render(); assert.ok(f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio').every((node) => node.props.disabled));
    const poll = { ...basePoll(), total_votes: 1, my_option_id: 6, options: [{ id: 5, text: 'В клубе', votes: 0 }, { id: 6, text: 'У въезда', votes: 1 }] };
    f.requests[0].resolve(poll); await flush(); f.render();
    assert.deepEqual(f.changes, [poll]); assert.equal(f.button('Проголосовать'), undefined); assert.ok(f.nodes('Text').some((node) => f.content(node) === '100%'));
  });
  await scenario('ambiguous vote error retains counts and can reconcile a closed poll', async () => {
    const poll = { ...basePoll(), total_votes: 1, my_option_id: 5 };
    const f = pollFixture(poll);
    f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio')[1].props.onPress(); f.render();
    f.button('Изменить голос').props.onPress(); f.requests[0].reject(Error('Соединение прервалось')); await flush(); f.render();
    assert.equal(f.changes.length, 0); assert.ok(f.nodes('Text').some((node) => f.content(node) === 'Соединение прервалось'));
    f.button('Обновить голосование').props.onPress();
    const closed = { ...poll, is_closed: true };
    f.requests[1].resolve({ poll: closed }); await flush(); f.render();
    assert.deepEqual(f.changes, [closed]); assert.ok(f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio').every((node) => node.props.disabled));
  });
  await scenario('refresh props cannot unlock an in-flight vote or discard its response', async () => {
    const f = pollFixture();
    f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio')[0].props.onPress(); f.render();
    const submit = f.button('Проголосовать').props.onPress; submit();
    f.setProps({ poll: { ...basePoll() } }); f.render(); submit();
    assert.equal(f.requests.length, 1);
    f.requests[0].resolve({ ...basePoll(), my_option_id: 5, total_votes: 1 }); await flush(); f.render();
    assert.equal(f.changes.length, 0, 'mutation response is not applied over a newer feed snapshot');
    assert.equal(f.requests[1].kind, 'refresh');
    f.requests[1].resolve({ poll: { ...basePoll(), my_option_id: 5, total_votes: 2 } }); await flush(); f.render();
    assert.equal(f.changes.length, 1);
    assert.equal(f.changes[0].total_votes, 2);
  });
  await scenario('replaced option IDs clear a draft choice and cannot be submitted by an old handler', async () => {
    const f = pollFixture();
    f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio')[0].props.onPress(); f.render();
    f.setProps({ poll: { ...basePoll(), options: [{ id: 15, text: 'Новый А', votes: 0 }, { id: 16, text: 'Новый Б', votes: 0 }] } });
    f.render(); assert.equal(f.button('Проголосовать').props.disabled, true);
    f.button('Проголосовать').props.onPress(); assert.equal(f.requests.length, 0);
    f.render(); assert.ok(f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio').every((node) => !node.props.accessibilityState.checked));
  });
  await scenario('close reconciles changed parent snapshots and ignores a second newer snapshot during reconciliation', async () => {
    const f = pollFixture(basePoll(), true);
    f.button('Завершить голосование').props.onPress(); f.render(); f.button('Завершить').props.onPress();
    f.setProps({ poll: { ...basePoll(), total_votes: 1 } }); f.render();
    f.requests[0].resolve({ ...basePoll(), is_closed: true }); await flush();
    assert.equal(f.changes.length, 0); assert.equal(f.requests[1].kind, 'refresh');
    f.setProps({ poll: { ...basePoll(), total_votes: 2, is_closed: true } }); f.render();
    f.requests[1].resolve({ poll: { ...basePoll(), total_votes: 1, is_closed: true } }); await flush(); f.render();
    assert.equal(f.changes.length, 0, 'the later feed snapshot wins over the reconciliation read');
    assert.ok(f.nodes('Text').some((node) => f.content(node).includes('Голосование обновилось')));
  });
  await scenario('late response for another post and unmounted card are ignored', async () => {
    for (const unmount of [false, true]) {
      const f = pollFixture();
      f.nodes('Pressable').filter((node) => node.props.accessibilityRole === 'radio')[0].props.onPress(); f.render(); f.button('Проголосовать').props.onPress();
      if (unmount) f.unmount(); else { f.setProps({ postId: 18, poll: { ...basePoll(), id: 3 } }); f.render(); }
      f.requests[0].resolve({ ...basePoll(), my_option_id: 5 }); await flush();
      assert.equal(f.changes.length, 0);
    }
  });
  await scenario('closing requires confirmation and does not send duplicate close requests', async () => {
    const f = pollFixture(basePoll(), true);
    f.button('Завершить голосование').props.onPress(); f.render(); assert.equal(f.requests.length, 0);
    const confirm = f.button('Завершить').props.onPress; confirm(); confirm(); assert.equal(f.requests.length, 1); assert.equal(f.requests[0].kind, 'close');
    f.requests[0].resolve({ ...basePoll(), is_closed: true }); await flush(); f.render();
    assert.equal(f.button('Завершить голосование'), undefined);
    const reader = pollFixture(); assert.equal(reader.button('Завершить голосование'), undefined);
  });
  await scenario('zero-vote results are readable and have no NaN percentages', async () => {
    const f = pollFixture(); f.button('Посмотреть результаты').props.onPress(); f.render();
    assert.equal(f.nodes('Text').filter((node) => f.content(node) === '0%').length, 2);
  });
  await scenario('post text is retained before media and expandable for administrators and residents', async () => {
    for (const admin of [false, true]) {
      const text = 'Длинный текст новости. '.repeat(60);
      const f = fixture('components/news/NewsPostCard.tsx', 'NewsPostCard', { post: { id: 17, text, media: [{ id: 'photo', kind: 'image', url: '/photo' }], author_name: 'Правление', created_at: '2026-09-28', version: 1, poll: basePoll() }, admin, onPollChange() {} }, { '@/services/newsService': helpers });
      f.render();
      let node = f.nodes('Text').find((item) => f.content(item) === text.trim()); assert.ok(node); assert.equal(node.props.numberOfLines, 7);
      f.button('Читать полностью').props.onPress(); f.render();
      node = f.nodes('Text').find((item) => f.content(item) === text.trim()); assert.equal(node.props.numberOfLines, undefined);
      assert.equal(f.nodes('NewsPollCard').length, 1);
    }
  });
  await scenario('text-only editor update omits poll and opens the saved post', async () => {
    const poll = { ...basePoll(), total_votes: 1, my_option_id: 5, can_edit: false };
    const f = editorFixture({ post: { id: 17, text: 'До', media: [], poll, version: 4 } });
    f.render(); await flush(); f.render();
    assert.equal(f.nodes('NewsPollEditor')[0].props.locked, true);
    f.nodes('TextInput')[0].props.onChangeText('После'); f.render();
    const submit = f.button('Сохранить изменения').props.onPress; submit(); submit();
    assert.equal(f.updates.length, 1); assert.deepEqual(f.updates[0], [17, { text: 'После', media_ids: [] }, 4]);
    f.pending.resolve({ id: 17 }); await flush();
    assert.deepEqual(f.navigation, [['Home', { screen: 'News', params: { postId: 17 } }]]);
  });
  await scenario('restored poll-only draft publishes with persistent payload and request ID', async () => {
    const poll = { question: 'Когда?', options: ['Утром', 'Вечером'] };
    const f = editorFixture({ draft: { text: '', media: [], requestId: 'draft-poll-id', poll } });
    f.render(); await flush(); f.render();
    assert.deepEqual(f.nodes('NewsPollEditor')[0].props.value, poll);
    assert.equal(f.button('Опубликовать').props.disabled, false);
    f.button('Опубликовать').props.onPress(); await flush();
    assert.deepEqual(f.publications[0], [{ text: '', media_ids: [], poll }, 'draft-poll-id']);
    assert.deepEqual(f.saves[0].pendingPayload, { text: '', media_ids: [], poll });
    f.pending.resolve({ id: 40 }); await flush();
  });
  await scenario('dispatcher cannot open the publication editor', async () => {
    const f = editorFixture({ user: { id: 2, isAdmin: true, staffRole: 'dispatcher' } });
    f.render(); await flush(); f.render();
    assert.equal(f.nodes('TextInput').length, 0); assert.equal(f.publications.length, 0);
    assert.equal(f.nodes('NewsState')[0].props.title, 'Публикации доступны администрации');
  });
  console.log(`PASS ${count} poll/card/editor state scenarios. Browser/native layout and real server behavior require separate checks.`);
}
main().catch((error) => { console.error(error); process.exitCode = 1; });
