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

async function run(request) {
  const pending = [];
  const res = await worker.fetch(request, ENV, { waitUntil: p => pending.push(p) });
  await Promise.all(pending);
  return res;
}

const dispatchesOf = calls =>
  calls.filter(c => c.url.endsWith("/dispatches")).map(c => JSON.parse(c.init.body));

test("tagging the bot in the PR's thread dispatches QA for that PR", async () => {
  const calls = mockServices("QA_TESTING", [
    { text: "🔗 *PR Link:* <https://github.com/acme/web/pull/5|View Pull Request>" },
  ]);
  await run(slackEvent({ type: "app_mention", text: "<@UBOT> run qa on this", channel: "C1", ts: "200.2", thread_ts: "100.1" }));
  assert.deepEqual(dispatchesOf(calls), [{
    event_type: "qa_web_preview",
    client_payload: { repository: "acme/web", pr_number: "5", slack_channel: "C1", slack_thread_ts: "100.1" },
  }]);
});

test("a coding request never starts QA", async () => {
  const calls = mockServices("CODE_DEVELOPMENT");
  await run(slackEvent({ type: "app_mention", text: "<@UBOT> acme/web add a footer", channel: "C1", ts: "300.3" }));
  const events = dispatchesOf(calls).map(d => d.event_type);
  assert.deepEqual(events, ["ai_developer_task"]);
});

test("the thread-reply copy of a QA request neither resumes coding nor dispatches twice", async () => {
  // Slack delivers a tagged thread reply twice: as app_mention and as message.
  const calls = mockServices("QA_TESTING", [
    { text: "🤖 *Antigravity AI Triggered*\n📦 *Repo:* `acme/web`\n📌 *Prompt:* `add a footer`" },
    { text: "🔗 *PR Link:* <https://github.com/acme/web/pull/5|View Pull Request>" },
  ]);
  await run(slackEvent({ type: "message", text: "<@UBOT> run qa on this", channel: "C1", ts: "200.2", thread_ts: "100.1" }));
  assert.deepEqual(dispatchesOf(calls), []);
});
