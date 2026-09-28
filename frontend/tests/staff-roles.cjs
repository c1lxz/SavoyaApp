const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const load = (file, modules) => {
  const source = fs.readFileSync(path.resolve(__dirname, '../src', file), 'utf8');
  const js = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020, jsx: ts.JsxEmit.React, esModuleInterop: true } }).outputText;
  const exports = {};
  new Function('require', 'exports', js)((name) => { assert.ok(name in modules, `Unexpected dependency ${name}`); return modules[name]; }, exports);
  return exports;
};
const roles = load('utils/roles.ts', {});
let checks = 0;
const check = (name, fn) => { fn(); checks++; console.log('PASS', name); };
check('legacy administrator retains access', () => assert.equal(roles.canManageNews({ isAdmin: true }), true));
check('administration can register and publish', () => {
  const user = { isAdmin: true, staffRole: 'administration' };
  assert.equal(roles.canRegisterUsers(user), true); assert.equal(roles.canManageNews(user), true);
});
check('dispatcher is staff without registration or news management', () => {
  const user = { isAdmin: true, staffRole: 'dispatcher' };
  assert.equal(roles.isStaff(user), true); assert.equal(roles.canRegisterUsers(user), false);
  assert.equal(roles.canManageNews(user), false); assert.equal(roles.canManageStaff(user), false);
});
check('resident cannot gain administration from a role field', () => assert.equal(roles.canManageNews({ isAdmin: false, staffRole: 'administration' }), false));
check('unknown role fails closed', () => assert.equal(roles.canRegisterUsers({ isAdmin: true, staffRole: 'invalid' }), false));
check('signed out permissions empty', () => assert.equal(roles.canManageNews(null), false));

const calls = [];
let response;
let sessionToken = 'synthetic-token';
const http = { apiRequest: async (...args) => { calls.push(args); return response; } };
const auth = load('services/api/apiAuthService.ts', {
  '@/services/api/httpClient': http,
  '@/services/api/tokenStore': { getAccessToken: () => sessionToken, restoreAccessToken: async () => sessionToken, setAccessToken: async (token) => { sessionToken = token; } },
  '@/services/newsNotifications': { unregisterNewsNotifications: async () => {} },
}).apiAuthService;
const admin = load('services/api/apiAdminService.ts', { '@/services/api/httpClient': http }).apiAdminService;

function renderHome(user) {
  const react = { createElement: (type, props, ...children) => ({ type, props: props || {}, children: children.flat() }) };
  const screen = load('screens/AdminHomeScreen.tsx', {
    react,
    '@expo/vector-icons': { MaterialCommunityIcons: 'Icon' },
    'react-native': { ScrollView: 'Scroll', Text: 'Text', View: 'View', useWindowDimensions: () => ({ width: 390, height: 844 }), StyleSheet: { create: (s) => s } },
    'react-native-safe-area-context': { SafeAreaView: 'SafeArea' },
    '@/components/AppBackground': { AppBackground: 'Background' },
    '@/components/AppButton': { AppButton: 'Button' },
    '@/components/ScreenHeader': { ScreenHeader: 'Header' },
    '@/store/authStore': { useAuthStore: (selector) => selector({ user, logout: async () => {} }) },
    '@/theme': { theme: { spacing: {}, colors: {}, radius: {} } },
    '@/utils/layout': { getLayoutMetrics: () => ({ isDesktop: false, formMaxWidth: 600, panelGap: 16 }) },
    '@/utils/backNavigation': { goBackOrHome: () => {} },
    '@/utils/roles': roles,
  }).AdminHomeScreen({ navigation: {} });
  const titles = [];
  function visit(node) { if (!node || typeof node !== 'object') return; if (node.type === 'Button') titles.push(node.props.title); node.children?.forEach(visit); }
  visit(screen); return titles;
}
check('dispatcher screen retains operational routes and news reading', () => {
  const titles = renderHome({ isAdmin: true, staffRole: 'dispatcher' });
  for (const name of ['Мониторинг', 'Пропуски', 'Пользователи', 'Открыть шлагбаум', 'Калитки', 'Новости посёлка']) assert.ok(titles.includes(name));
  assert.ok(!titles.includes('Опубликовать новость')); assert.ok(!titles.includes('Сотрудники и роли'));
});
check('administration screen exposes news and staff management', () => {
  const titles = renderHome({ isAdmin: true, staffRole: 'administration' });
  assert.ok(titles.includes('Опубликовать новость')); assert.ok(titles.includes('Сотрудники и роли'));
});

(async () => {
  response = { success: true, access_token: 'synthetic-token', user: { id: '4', login: 'dispatcher', fullName: 'Test Staff', isAdmin: true, staffRole: 'dispatcher' } };
  const compat = await auth.login('dispatcher', 'synthetic-password');
  check('compat login preserves dispatcher restriction', () => assert.equal(roles.canManageNews(compat.user), false));
  response = { token_type: 'bearer', access_token: 'synthetic-token', user: { id: 4, phone: 'test-phone', is_admin: true, staff_role: 'dispatcher' } };
  const native = await auth.login('dispatcher', 'synthetic-password');
  check('native login preserves dispatcher restriction', () => assert.equal(native.user.staffRole, 'dispatcher'));
  response = { id: '4', login: 'dispatcher', isAdmin: true, staffRole: 'administration' };
  const refreshed = await auth.getCurrentUser(true);
  check('session refresh applies role changes', () => assert.equal(refreshed.staffRole, 'administration'));
  const staff = { id: 4, login: 'dispatcher', is_admin: true, staff_role: 'dispatcher', is_active: true };
  response = { total: 1, items: [staff] };
  const result = await admin.getUsers({ accountType: 'staff', limit: 50, offset: 50 });
  check('staff list uses explicit account filter and maps role', () => {
    const params = new URL('https://example.test' + calls.at(-1)[0]).searchParams;
    assert.equal(params.get('account_type'), 'staff'); assert.equal(params.get('offset'), '50');
    assert.equal(result.items[0].staffRole, 'dispatcher');
  });
  response = staff;
  await admin.createUser({ fullName: 'Test Staff', phoneNumber: 'test-phone', plotNumber: '', staffRole: 'dispatcher' });
  check('staff creation sends selected role without a required resident plot', () => {
    assert.equal(calls.at(-1)[1].body.staff_role, 'dispatcher');
    assert.equal(calls.at(-1)[1].body.plot_number, undefined);
  });
  await admin.createUser({ fullName: 'Test Resident', phoneNumber: 'test-phone', plotNumber: '1' });
  check('resident creation does not gain a staff role', () => assert.equal(calls.at(-1)[1].body.staff_role, undefined));
  await admin.setStaffRole('4', 'administration');
  check('role change uses PATCH with target role', () => {
    assert.equal(calls.at(-1)[0], '/api/admin/users/4/role'); assert.equal(calls.at(-1)[1].method, 'PATCH');
    assert.deepEqual(calls.at(-1)[1].body, { staff_role: 'administration' });
  });
  console.log(`${checks} staff role scenarios passed (controlled UI/API harness; not device rendering).`);
})().catch((e) => { console.error(e); process.exitCode = 1; });
