import { test, afterEach } from "node:test";
import assert from "node:assert/strict";

import worker from "../slack-worker.js";

const ENV = {
  GITHUB_PAT: "pat",
  GEMINI_API_KEY: "key",
  SLACK_BOT_TOKEN: "xoxb",
  WORKFLOW_REPO_OWNER: "bhaveshupadhyay",
  WORKFLOW_REPO_NAME: "github_automation",
  DEFAULT_GITHUB_REPO: "acme/api",
};
const REGISTRY = { targets: { "acme/web": { platform: "web", backend_repo: "acme/api" } } };
const realFetch = globalThis.fetch;

const BOT_THREAD = [
  { ts: "100.1", text: "🤖 *Antigravity AI Triggered*\n📦 *Repo:* `acme/web`\n📌 *Prompt:* `add an admin panel`", bot_id: "B1" },
  { ts: "150.0", text: "🔗 *PR Link:* <https://github.com/acme/web/pull/5|View Pull Request>", bot_id: "B1" },
];
const QUESTION = { ts: "210.0", bot_id: "B1", text: "🧪 *QA for* `acme/web#5` — *which backend should it run against?* Reply with:\n• …" };

afterEach(() => {
  globalThis.fetch = realFetch;
});

/** Mocks Gemini (returning `intent`), Slack and GitHub; records every call. */
function mockServices(intent, threadMessages = []) {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    const href = String(url);
    calls.push({ url: href, init });
    if (href.includes("generativelanguage.googleapis.com")) {
      const text = JSON.stringify({ intent });
      return Response.json({ candidates: [{ content: { parts: [{ text }] } }] });
    }
    if (href.includes("conversations.replies")) return Response.json({ ok: true, messages: threadMessages });
    if (href.includes("chat.postMessage")) return Response.json({ ok: true, ts: "9.9" });
    if (href.includes("/contents/contracts/qa-targets.json")) return Response.json(REGISTRY);
    if (href.endsWith("/dispatches")) return new Response(null, { status: 204 });
    return new Response("unexpected", { status: 500 });
  };
  return calls;
}

function slackEvent(event) {
  return new Request("https://worker.example/", {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ type: "event_callback", event }),
  });
}

async function run(event) {
  const pending = [];
  await worker.fetch(slackEvent(event), ENV, { waitUntil: p => pending.push(p) });
  await Promise.all(pending);
}

const dispatchesOf = calls =>
  calls.filter(c => c.url.endsWith("/dispatches")).map(c => JSON.parse(c.init.body));
const postsOf = calls =>
  calls.filter(c => c.url.includes("chat.postMessage")).map(c => JSON.parse(c.init.body));

test("asking for QA in the PR's thread asks which backend, and starts nothing yet", async () => {
  const calls = mockServices("QA_TESTING", BOT_THREAD);
  await run({ type: "app_mention", text: "<@UBOT> run qa on this", channel: "C1", ts: "200.2", thread_ts: "100.1" });
  assert.deepEqual(dispatchesOf(calls), []);
  const [question] = postsOf(calls);
  assert.match(question.text, /QA for\* `acme\/web#5` — \*which backend/);
  assert.equal(question.thread_ts, "100.1");
});

test("the backend PR answer starts QA of the frontend PR against it", async () => {
  const calls = mockServices("CODE_DEVELOPMENT", [...BOT_THREAD, QUESTION]);
  // Slack delivers a tagged reply both ways; the thread-reply copy handles it.
  await run({ type: "app_mention", text: "<@UBOT> acme/api#8", channel: "C1", ts: "220.0", thread_ts: "100.1" });
  await run({ type: "message", text: "<@UBOT> acme/api#8", channel: "C1", ts: "220.0", thread_ts: "100.1" });
  assert.deepEqual(dispatchesOf(calls), [{
    event_type: "qa_web_preview",
    client_payload: { repository: "acme/web", pr_number: "5", backend: "acme/api#8", slack_channel: "C1", slack_thread_ts: "100.1" },
  }]);
});

test("an untagged `main` answer also starts QA, and never resumes coding", async () => {
  const calls = mockServices("CODE_DEVELOPMENT", [...BOT_THREAD, QUESTION]);
  await run({ type: "message", text: "main", channel: "C1", ts: "220.0", thread_ts: "100.1" });
  const events = dispatchesOf(calls);
  assert.equal(events.length, 1);
  assert.equal(events[0].event_type, "qa_web_preview");
  assert.equal(events[0].client_payload.backend, "main");
});

test("a coding request never starts QA", async () => {
  const calls = mockServices("CODE_DEVELOPMENT");
  await run({ type: "app_mention", text: "<@UBOT> acme/web add an admin panel", channel: "C1", ts: "300.3" });
  assert.deepEqual(dispatchesOf(calls).map(d => d.event_type), ["ai_developer_task"]);
});

test("the thread-reply copy of a QA request neither resumes coding nor dispatches", async () => {
  const calls = mockServices("QA_TESTING", BOT_THREAD);
  await run({ type: "message", text: "<@UBOT> run qa on this", channel: "C1", ts: "200.2", thread_ts: "100.1" });
  assert.deepEqual(dispatchesOf(calls), []);
});
