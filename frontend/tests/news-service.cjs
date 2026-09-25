const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const ts = require("typescript");

// These exercise the actual service with controllable transport/storage. They
// verify client contracts, not React rendering, real uploads or server delivery.
const source = fs.readFileSync(
  path.resolve(__dirname, "../src/services/newsService.ts"),
  "utf8",
);
const compiled = ts.transpileModule(source, {
  compilerOptions: {
    module: ts.ModuleKind.CommonJS,
    target: ts.ScriptTarget.ES2020,
    esModuleInterop: true,
  },
}).outputText;
const MEDIA = {
  id: "a".repeat(32),
  name: "План посёлка.pdf",
  mime_type: "application/pdf",
  size_bytes: 512,
  kind: "document",
  url: "/api/news/media/a/content?expires=1&signature=test",
  thumbnail_url: null,
};

function fixture(options = {}) {
  const requests = [],
    xhrs = [],
    apiCalls = [],
    timers = new Map();
  const store = options.store || new Map();
  let timerId = 0;
  class FormDataMock {
    entries = [];
    append(...args) {
      this.entries.push(args);
    }
  }
  class XhrMock {
    upload = {};
    headers = {};
    status = 0;
    responseText = "";
    constructor() {
      xhrs.push(this);
    }
    open(method, url) {
      this.method = method;
      this.url = url;
    }
    setRequestHeader(key, value) {
      this.headers[key] = value;
    }
    send(body) {
      this.body = body;
    }
    abort() {
      this.aborted = true;
      this.onabort?.();
    }
    progress(loaded, total = 100) {
      this.upload.onprogress?.({ lengthComputable: true, loaded, total });
    }
    respond(status, value) {
      this.status = status;
      this.responseText =
        typeof value === "string" ? value : JSON.stringify(value);
      this.onload();
    }
  }
  const storage = {
    getItem: async (key) => {
      if (options.failRead) throw Error("storage unavailable");
      return store.get(key) ?? null;
    },
    setItem: async (key, value) => {
      if (options.failWrite) throw Error("quota exceeded");
      store.set(key, value);
    },
    removeItem: async (key) => store.delete(key),
  };
  const requireMock = (name) =>
    ({
      "react-native": { Platform: { OS: options.platform || "android" } },
      "@react-native-async-storage/async-storage": storage,
      "@/services/api/config": {
        API_BASE_URL: options.baseUrl || "https://example.test",
      },
      "@/services/api/tokenStore": {
        getAccessToken: () => "test-session-token",
      },
      "@/services/api/httpClient": {
        apiRequest: async (...args) => {
          apiCalls.push(args);
          return options.apiResult;
        },
      },
    })[name];
  const fetchMock = async (url, args) => {
    requests.push({ url, ...args });
    if (!options.fetch) throw Error("unexpected fetch");
    return options.fetch(url, args);
  };
  const mod = { exports: {} };
  new Function(
    "require",
    "module",
    "exports",
    "XMLHttpRequest",
    "FormData",
    "fetch",
    "setTimeout",
    "clearTimeout",
    "window",
    compiled,
  )(
    requireMock,
    mod,
    mod.exports,
    XhrMock,
    FormDataMock,
    fetchMock,
    (callback, delay) => {
      const id = ++timerId;
      timers.set(id, { callback, delay });
      return id;
    },
    (id) => timers.delete(id),
    options.platform === "web"
      ? { location: { origin: "https://example.test" } }
      : undefined,
  );
  return { api: mod.exports, requests, xhrs, apiCalls, store, timers };
}

const response = (status, data) => ({
  ok: status >= 200 && status < 300,
  status,
  text: async () => (typeof data === "string" ? data : JSON.stringify(data)),
});
const isUncertain = (expected) => (error) => error.uncertain === expected;
let passed = 0;
async function scenario(name, run) {
  await run();
  passed += 1;
  console.log(`PASS ${name}`);
}

async function main() {
  await scenario(
    "accepted-but-lost publication response replays persisted request against mock idempotent server",
    async () => {
      let dropped = false,
        created = 0;
      const posts = new Map();
      const server = async (_url, args) => {
        const body = JSON.parse(args.body);
        if (!posts.has(body.request_id))
          posts.set(body.request_id, {
            id: ++created,
            text: body.text,
            media: [MEDIA],
            version: 1,
          });
        if (!dropped) {
          dropped = true;
          throw Error("response connection lost after commit");
        }
        return response(201, posts.get(body.request_id));
      };
      const first = fixture({ fetch: server });
      const payload = { text: "Плановые работы", media_ids: [MEDIA.id] };
      const draft = {
        text: payload.text,
        media: [MEDIA],
        requestId: first.api.createNewsRequestId(),
        pendingPayload: payload,
      };
      await first.api.saveNewsDraft(7, draft);
      await assert.rejects(
        first.api.publishNews(payload, draft.requestId),
        isUncertain(true),
      );
      assert.equal(
        first.requests.length,
        1,
        "the client does not automatically repeat a possibly committed POST",
      );
      const restoredClient = fixture({ store: first.store, fetch: server });
      const restored = await restoredClient.api.loadNewsDraft(7);
      const post = await restoredClient.api.publishNews(
        restored.pendingPayload,
        restored.requestId,
      );
      assert.equal(post.id, 1);
      assert.equal(created, 1);
      assert.deepEqual(
        JSON.parse(first.requests[0].body),
        JSON.parse(restoredClient.requests[0].body),
      );
      assert.equal(
        first.requests[0].headers.Authorization,
        "Bearer test-session-token",
      );
    },
  );

  await scenario(
    "confirmed rejection versus unknown delivery is distinguished without automatic retry",
    async () => {
      for (const [status, body, uncertain] of [
        [409, { detail: "Конфликт публикации" }, false],
        [413, "too large", false],
        [500, { detail: "storage unavailable" }, true],
        [201, "broken JSON", true],
      ]) {
        const f = fixture({ fetch: async () => response(status, body) });
        await assert.rejects(
          f.api.publishNews(
            { text: "Новость", media_ids: [] },
            "request-12345",
          ),
          isUncertain(uncertain),
        );
        assert.equal(f.requests.length, 1);
        assert.equal(
          f.timers.size,
          0,
          "publication timer released after response",
        );
      }
    },
  );

  await scenario(
    "publication timeout aborts transport but remains unknown delivery",
    async () => {
      const f = fixture({
        fetch: (_url, args) =>
          new Promise((_, reject) =>
            args.signal.addEventListener("abort", () =>
              reject(Object.assign(Error("aborted"), { name: "AbortError" })),
            ),
          ),
      });
      const publication = f.api.publishNews(
        { text: "Новость", media_ids: [] },
        "request-timeout",
      );
      const timer = [...f.timers.values()][0];
      assert.equal(timer.delay, 45000);
      timer.callback();
      await assert.rejects(publication, isUncertain(true));
      assert.equal(f.requests.length, 1);
      assert.equal(f.requests[0].signal.aborted, true);
    },
  );

  await scenario(
    "100MiB browser attachment is passed as the original File without JS byte reads",
    async () => {
      const f = fixture({ platform: "web" });
      const file = {
        name: "large-video.mp4",
        arrayBuffer() {
          throw Error("whole file read");
        },
        text() {
          throw Error("whole file read");
        },
        toJSON() {
          throw Error("whole file serialization");
        },
      };
      const progress = [];
      const upload = f.api.uploadNewsFile(
        {
          uri: "blob:source",
          name: file.name,
          mimeType: "video/mp4",
          size: f.api.NEWS_FILE_LIMIT,
          file,
        },
        (value) => progress.push(value),
      );
      const xhr = f.xhrs[0];
      assert.equal(xhr.body.entries[0][1], file);
      assert.equal(
        xhr.headers["Content-Type"],
        undefined,
        "native/browser transport generates multipart boundary",
      );
      xhr.progress(100);
      assert.equal(
        progress.at(-1),
        99,
        "sent bytes are not server acknowledgement",
      );
      xhr.respond(201, MEDIA);
      assert.deepEqual(await upload.promise, MEDIA);
      assert.equal(progress.at(-1), 100);
    },
  );

  await scenario(
    "Android content URI upload preserves filename and MIME without base64",
    async () => {
      const f = fixture();
      const file = {
        uri: "content://provider/42",
        name: "Документ №1.pdf",
        mimeType: "application/pdf",
        size: 512,
      };
      const job = f.api.uploadNewsFile(file, () => {});
      assert.deepEqual(f.xhrs[0].body.entries[0], [
        "file",
        { uri: file.uri, name: file.name, type: file.mimeType },
      ]);
      f.xhrs[0].respond(201, MEDIA);
      await job.promise;
    },
  );

  await scenario(
    "oversized file and missing browser File fail before a request is sent",
    async () => {
      const native = fixture();
      const web = fixture({ platform: "web" });
      await assert.rejects(
        native.api.uploadNewsFile(
          {
            uri: "file:///large",
            name: "large",
            mimeType: "x/test",
            size: native.api.NEWS_FILE_LIMIT + 1,
          },
          () => {},
        ).promise,
        /100/,
      );
      await assert.rejects(
        web.api.uploadNewsFile(
          { uri: "blob:lost", name: "lost", mimeType: "x/test" },
          () => {},
        ).promise,
        /заново/,
      );
      assert.equal(native.xhrs[0].body, undefined);
      assert.equal(web.xhrs[0].body, undefined);
    },
  );

  await scenario(
    "cancelled upload never reports server success and the same source can be retried",
    async () => {
      const f = fixture();
      const file = {
        uri: "file:///source.pdf",
        name: "source.pdf",
        mimeType: "application/pdf",
        size: 512,
      };
      const progress = [];
      const first = f.api.uploadNewsFile(file, (value) => progress.push(value));
      f.xhrs[0].progress(50);
      first.cancel();
      await assert.rejects(first.promise, /отменена/);
      assert.ok(!progress.includes(100));
      const retry = f.api.uploadNewsFile(file, () => {});
      f.xhrs[1].respond(201, MEDIA);
      assert.deepEqual(await retry.promise, MEDIA);
    },
  );

  await scenario(
    "network failure, upload timeout, HTTP413 and malformed success all reject",
    async () => {
      for (const fail of [
        (xhr) => xhr.onerror(),
        (xhr) => xhr.ontimeout(),
        (xhr) => xhr.respond(413, "too large"),
        (xhr) => xhr.respond(201, "not JSON"),
      ]) {
        const f = fixture();
        const values = [];
        const job = f.api.uploadNewsFile(
          {
            uri: "file:///source",
            name: "source",
            mimeType: "x/test",
            size: 10,
          },
          (value) => values.push(value),
        );
        fail(f.xhrs[0]);
        await assert.rejects(job.promise);
        assert.ok(!values.includes(100));
      }
    },
  );

  await scenario(
    "drafts isolate accounts, preserve pending payload and clearing one does not clear another",
    async () => {
      const f = fixture();
      const draft = {
        text: "Черновик",
        media: [MEDIA],
        requestId: "draft-request",
        pendingPayload: { text: "Черновик", media_ids: [MEDIA.id] },
      };
      await f.api.saveNewsDraft(1, draft);
      await f.api.saveNewsDraft(2, { ...draft, text: "Другой" });
      assert.deepEqual(await f.api.loadNewsDraft(1), draft);
      await f.api.clearNewsDraft(1);
      assert.equal(await f.api.loadNewsDraft(1), null);
      assert.equal((await f.api.loadNewsDraft(2)).text, "Другой");
      const failing = fixture({ failWrite: true });
      await assert.rejects(failing.api.saveNewsDraft(1, draft), /quota/);
      f.store.set("savoya:news-draft:v1:3", "broken-json");
      assert.equal(await f.api.loadNewsDraft(3), null);
    },
  );

  await scenario(
    "signed media URLs remain intact and external or insecure origins are rejected",
    async () => {
      const f = fixture();
      const signed = "/api/news/media/a/content?expires=123&signature=a%2Bb";
      assert.equal(f.api.newsUrl(signed), `https://example.test${signed}`);
      for (const url of [
        "https://other.test/file",
        "//other.test/file",
        "http://example.test/file",
        "data:text/html,hello",
      ])
        assert.throws(() => f.api.newsUrl(url));
      assert.equal(
        fixture({ baseUrl: "http://127.0.0.1:8015" }).api.newsUrl("/api/news"),
        "http://127.0.0.1:8015/api/news",
      );
    },
  );

  await scenario(
    "optimistic versions and archive cursor reach the backend request unchanged",
    async () => {
      const f = fixture();
      const payload = { text: "Новая редакция", media_ids: [MEDIA.id] };
      await f.api.updateNews(17, payload, 4);
      await f.api.deleteNews({ id: 17, version: 4 });
      await f.api.getNews(10, 17);
      assert.deepEqual(f.apiCalls[0], [
        "/api/news/17",
        { method: "PUT", body: { ...payload, version: 4 } },
      ]);
      assert.deepEqual(f.apiCalls[1], [
        "/api/news/17?version=4",
        { method: "DELETE" },
      ]);
      assert.equal(f.apiCalls[2][0], "/api/news?limit=10&before_id=17");
    },
  );

  await scenario(
    "repeated upload percentages do not flood UI and only acknowledgement emits100",
    async () => {
      const perf = fixture();
      let progressCallbacks = 0;
      const job = perf.api.uploadNewsFile(
        {
          uri: "file:///large",
          name: "large",
          mimeType: "x/test",
          size: 100 * 1024 * 1024,
        },
        () => {
          progressCallbacks += 1;
        },
      );
      for (let i = 0; i < 1000; i++) perf.xhrs[0].progress(500000 + i, 1000000);
      perf.xhrs[0].progress(0, 0);
      perf.xhrs[0].progress(10, 100);
      assert.equal(
        progressCallbacks,
        1,
        "same or lower percentage and unknown totals cannot retrigger rendering",
      );
      perf.xhrs[0].respond(201, MEDIA);
      await job.promise;
      assert.equal(progressCallbacks, 2);
      console.log(
        `DIAGNOSTIC: 1000 progress events within the same rounded percentage emitted ${progressCallbacks} callbacks (including completion).`,
      );
    },
  );

  await scenario(
    "gallery source policy requests exactly one original and never falls back to adjacent originals",
    async () => {
      const f = fixture();
      const photos = Array.from({ length: 10 }, (_, i) => ({
        ...MEDIA,
        id: `image-${i}`,
        kind: "image",
        url: `/original-${i}`,
        thumbnail_url: `/thumbnail-${i}`,
      }));
      for (const selected of [0, 5, 9]) {
        const sources = photos.map((photo, i) =>
          f.api.newsViewerSource(photo, i === selected),
        );
        assert.equal(
          sources.filter((source) => source.startsWith("/original-")).length,
          1,
        );
        assert.equal(sources[selected], `/original-${selected}`);
        assert.equal(
          f.api.newsViewerSource(
            { ...photos[selected], thumbnail_url: null },
            false,
          ),
          null,
        );
      }
    },
  );

  await scenario(
    "draft autosave key ignores refreshed media URLs and detects author changes plus pending publication",
    async () => {
      const f = fixture();
      const otherMedia = { ...MEDIA, id: "b".repeat(32) };
      const draft = {
        text: "Сохранить сразу",
        media: [MEDIA, otherMedia],
        requestId: "pending-draft-key",
      };
      const key = f.api.newsDraftContentKey(draft);
      const refreshed = {
        ...draft,
        media: draft.media.map((media) => ({
          ...media,
          url: `${media.url}&renewed=1`,
          thumbnail_url: "/new-thumbnail",
        })),
      };
      assert.equal(
        f.api.newsDraftContentKey(refreshed),
        key,
        "fresh signed URLs are not a new draft",
      );
      for (const changed of [
        { ...draft, text: "Текст изменён" },
        { ...draft, media: [MEDIA] },
        { ...draft, media: [otherMedia, MEDIA] },
        { ...draft, requestId: "another-request" },
        {
          ...draft,
          pendingPayload: {
            text: draft.text,
            media_ids: draft.media.map((media) => media.id),
          },
        },
      ])
        assert.notEqual(f.api.newsDraftContentKey(changed), key);
      // The key is only a scheduling dependency; durable storage keeps the actual snapshot.
      await f.api.saveNewsDraft(4, refreshed);
      assert.deepEqual(await f.api.loadNewsDraft(4), refreshed);
    },
  );
  console.log(
    `PASS ${passed} news service scenarios. Media UI, native device behavior and real server delivery require separate integration checks.`,
  );
}
main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
