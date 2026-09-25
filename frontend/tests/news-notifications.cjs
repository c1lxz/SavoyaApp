const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
// Behavioral service tests with mocked Android SDK, network, storage and timers.
// These do not mount the React notification bridge or prove live FCM delivery.
const root = path.resolve(__dirname, "..");
const ts = require("typescript");
const code = ts.transpileModule(
  fs.readFileSync(path.join(root, "src/services/newsNotifications.ts"), "utf8"),
  {
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2020,
      esModuleInterop: true,
    },
  },
).outputText;
const deferred = () => {
  let resolve, reject;
  const promise = new Promise((a, b) => {
    resolve = a;
    reject = b;
  });
  return { promise, resolve, reject };
};
const flush = async () => {
  for (let i = 0; i < 50; i++) await Promise.resolve();
};

function fixture(options = {}) {
  let accessToken = "account-a",
    clock = 0,
    timerId = 0;
  const timers = new Map(),
    requests = [],
    stored = new Map(),
    states = [];
  const fakeSetTimeout = (callback, delay) => {
    const id = ++timerId;
    timers.set(id, { at: clock + delay, callback });
    return id;
  };
  const fakeClearTimeout = (id) => timers.delete(id);
  const storage = {
    getItem: async (key) => stored.get(key) || null,
    setItem: async (key, value) => {
      if (options.storageWait) await options.storageWait(value);
      stored.set(key, value);
    },
    removeItem: async (key) => {
      stored.delete(key);
    },
  };
  const native = {
    AndroidImportance: { DEFAULT: 3 },
    setNotificationChannelAsync: options.channel || (async () => {}),
    getPermissionsAsync: async () => ({ granted: true, canAskAgain: true }),
    requestPermissionsAsync: async () => ({ granted: true, canAskAgain: true }),
    getDevicePushTokenAsync:
      options.nativeToken || (async () => ({ data: "native-device-a" })),
    unregisterForNotificationsAsync: options.unregister || (async () => {}),
  };
  const fetchMock = async (_url, args) => {
    const request = {
      method: args.method,
      authorization: args.headers.Authorization,
      token: JSON.parse(args.body).token,
    };
    requests.push(request);
    if (options.network) await options.network(request);
    return { ok: true };
  };
  const mod = { exports: {} };
  const requireMock = (name) =>
    ({
      "@react-native-async-storage/async-storage": storage,
      "expo-constants": { expoConfig: { extra: { newsPushConfigured: true } } },
      "react-native": { Platform: { OS: "android" } },
      "@/services/api/tokenStore": { getAccessToken: () => accessToken },
      "@/services/newsService": {
        newsUrl: (url) => `https://example.test${url}`,
      },
      "expo-notifications": native,
    })[name];
  new Function(
    "require",
    "module",
    "exports",
    "setTimeout",
    "clearTimeout",
    "AbortController",
    "fetch",
    code,
  )(
    requireMock,
    mod,
    mod.exports,
    fakeSetTimeout,
    fakeClearTimeout,
    AbortController,
    fetchMock,
  );
  const api = mod.exports;
  api.subscribeNotifications(() => states.push(api.getNotificationStatus()));
  return {
    api,
    requests,
    stored,
    states,
    setAccessToken(value) {
      accessToken = value;
    },
    async advance(ms) {
      const until = clock + ms;
      for (;;) {
        const next = [...timers.entries()]
          .filter(([, timer]) => timer.at <= until)
          .sort((a, b) => a[1].at - b[1].at)[0];
        if (!next) break;
        clock = next[1].at;
        timers.delete(next[0]);
        next[1].callback();
        await flush();
      }
      clock = until;
      await flush();
    },
  };
}

async function main() {
  {
    const token = deferred();
    const f = fixture({
      nativeToken: () => token.promise,
      unregister: () => new Promise(() => {}),
    });
    f.api.beginNewsNotificationSession();
    const registration = f.api.registerNewsNotifications();
    await flush();
    let loggedOut = false;
    const logout = f.api.unregisterNewsNotifications().then(() => {
      loggedOut = true;
    });
    await flush();
    await f.advance(7999);
    assert.equal(loggedOut, false);
    await f.advance(1);
    await logout;
    assert.equal(loggedOut, true);
    f.setAccessToken(null);
    token.resolve({ data: "late-native-token" });
    await registration;
    assert.equal(f.requests.filter((r) => r.method === "POST").length, 0);
    assert.equal(f.stored.size, 0);
    assert.equal(f.api.getNotificationStatus(), "idle");
  }
  {
    const post = deferred();
    const f = fixture({
      network: (r) => (r.method === "POST" ? post.promise : Promise.resolve()),
    });
    f.api.beginNewsNotificationSession();
    const registration = f.api.registerNewsNotifications();
    await flush();
    assert.equal(f.requests[0].method, "POST");
    await f.api.unregisterNewsNotifications();
    f.setAccessToken(null);
    post.resolve();
    await registration;
    assert.equal(f.requests.filter((r) => r.method === "DELETE").length, 2);
    assert.ok(f.requests.every((r) => r.authorization === "Bearer account-a"));
    assert.equal(f.stored.size, 0);
    assert.equal(f.api.getNotificationStatus(), "idle");
  }
  {
    const oldPost = deferred(),
      newPost = deferred();
    let device = "old-device";
    const f = fixture({
      nativeToken: async () => ({ data: device }),
      network: (r) =>
        r.method !== "POST"
          ? Promise.resolve()
          : r.token === "old-device"
            ? oldPost.promise
            : newPost.promise,
    });
    f.api.beginNewsNotificationSession();
    const oldAttempt = f.api.registerNewsNotifications();
    await flush();
    await f.api.unregisterNewsNotifications();
    f.setAccessToken("account-b");
    device = "new-device";
    f.api.beginNewsNotificationSession();
    const newAttempt = f.api.registerNewsNotifications();
    await flush();
    oldPost.resolve();
    await oldAttempt;
    assert.equal(
      f.api.registerNewsNotifications(),
      newAttempt,
      "old finally cannot clear current single-flight attempt",
    );
    newPost.resolve();
    await newAttempt;
    assert.equal(f.stored.get("savoya:news-device:v1"), "new-device");
    assert.equal(f.api.getNotificationStatus(), "enabled");
    assert.equal(
      f.requests.at(-1).method,
      "DELETE",
      "late old response is followed by cleanup",
    );
    assert.ok(
      f.requests
        .filter((r) => r.method === "DELETE")
        .every(
          (r) =>
            r.authorization === "Bearer account-a" && r.token === "old-device",
        ),
    );
  }
  {
    const token = deferred();
    const f = fixture({ nativeToken: () => token.promise });
    f.api.beginNewsNotificationSession();
    const first = f.api.registerNewsNotifications();
    await flush();
    assert.equal(
      f.api.registerNewsNotifications(true),
      first,
      "repeated registration in the same session reuses its pending request",
    );
    token.resolve({ data: "profile-device" });
    await first;
    assert.equal(f.requests.filter((r) => r.method === "POST").length, 1);
    assert.equal(f.api.getNotificationStatus(), "enabled");
  }
  {
    const hung = deferred();
    const f = fixture({ nativeToken: () => hung.promise });
    f.api.beginNewsNotificationSession();
    const attempt = f.api.registerNewsNotifications();
    await flush();
    await f.advance(15000);
    await attempt;
    assert.equal(f.api.getNotificationStatus(), "error");
    assert.equal(f.requests.length, 0);
  }
  {
    const firstWrite = deferred();
    let device = "old-device";
    const f = fixture({
      nativeToken: async () => ({ data: device }),
      storageWait: (value) =>
        value === "old-device" ? firstWrite.promise : Promise.resolve(),
    });
    f.api.beginNewsNotificationSession();
    const oldAttempt = f.api.registerNewsNotifications();
    await flush();
    const logout = f.api.unregisterNewsNotifications();
    await flush();
    await f.advance(8000);
    await logout;
    f.setAccessToken("account-b");
    device = "new-device";
    f.api.beginNewsNotificationSession();
    const newAttempt = f.api.registerNewsNotifications();
    await flush();
    firstWrite.resolve();
    await oldAttempt;
    await newAttempt;
    assert.equal(
      f.stored.get("savoya:news-device:v1"),
      "new-device",
      "slow old storage write cannot survive queued logout/new-session writes",
    );
    assert.equal(f.api.getNotificationStatus(), "enabled");
  }
  console.log(
    "PASS 6 notification service scenarios: bounded hung-GMS logout and late native result; late POST compensation; account isolation; in-flight request reuse; native timeout; queued storage ordering",
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
