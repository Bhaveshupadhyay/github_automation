import { test } from "node:test";
import assert from "node:assert/strict";

import {
  extractPullRequestRef,
  findLatestPullRequestInThread,
  findTarget,
  QaRequestService,
} from "../src/services/qaRequestService.js";

const REGISTRY = {
  targets: {
    "Acme/Web": { platform: "web", backend_repo: "acme/api" },
    "acme/app": { platform: "mobile", backend_repo: "acme/api" },
  },
};

function fakes({ threadMessages = [], dispatchOk = true } = {}) {
  const posted = [];
  const dispatched = [];
  const slack = {
    async postMessage(channel, text, ts) { posted.push({ channel, text, ts }); return "1.1"; },
    async fetchThreadMessages() { return threadMessages; },
  };
  const github = {
    async dispatchEvent(eventType, payload) { dispatched.push({ eventType, payload }); return dispatchOk; },
  };
  const registry = { async getRegistry() { return REGISTRY; } };
  return { service: new QaRequestService(slack, github, registry), posted, dispatched };
}

test("reads a PR link as Slack renders it", () => {
  assert.deepEqual(
    extractPullRequestRef("test <https://github.com/acme/web/pull/12|this PR> please"),
    { repository: "acme/web", number: 12 }
  );
});

test("reads the owner/repo#N short form", () => {
  assert.deepEqual(extractPullRequestRef("qa acme/web#7"), { repository: "acme/web", number: 7 });
});

test("finds no PR in a message without one", () => {
  assert.equal(extractPullRequestRef("please run qa"), null);
});

test("uses the latest PR linked in the thread", () => {
  const messages = [
    { text: "🤖 Antigravity AI Triggered" },
    { text: "🔗 *PR Link:* <https://github.com/acme/web/pull/3|View Pull Request>" },
    { text: "updated: <https://github.com/acme/web/pull/4|View Pull Request>" },
    { text: "@bot now test it" },
  ];
  assert.deepEqual(findLatestPullRequestInThread(messages), { repository: "acme/web", number: 4 });
});

test("registry lookup ignores case, like GitHub", () => {
  assert.equal(findTarget(REGISTRY, "ACME/WEB").platform, "web");
  assert.equal(findTarget(REGISTRY, "acme/none"), null);
});

test("dispatches the PR the bot opened in this thread, replying in the thread", async () => {
  const { service, posted, dispatched } = fakes({
    threadMessages: [{ text: "🔗 *PR Link:* <https://github.com/acme/web/pull/9|View Pull Request>" }],
  });
  const ok = await service.handle({ text: "run qa on it", channelId: "C1", threadTs: "100.1", replyTs: "100.1" });
  assert.equal(ok, true);
  assert.deepEqual(dispatched, [{
    eventType: "qa_web_preview",
    payload: { repository: "acme/web", pr_number: "9", slack_channel: "C1", slack_thread_ts: "100.1" },
  }]);
  assert.match(posted[0].text, /QA testing started/);
  assert.equal(posted[0].ts, "100.1");
});

test("an explicit PR in the message wins over the thread's", async () => {
  const { service, dispatched } = fakes({
    threadMessages: [{ text: "<https://github.com/acme/web/pull/9|x>" }],
  });
  await service.handle({ text: "test acme/app#2", channelId: "C1", threadTs: "100.1", replyTs: "100.1" });
  assert.equal(dispatched[0].eventType, "qa_mobile_preview");
  assert.equal(dispatched[0].payload.pr_number, "2");
});

test("asks which PR when none can be found, and dispatches nothing", async () => {
  const { service, posted, dispatched } = fakes();
  const ok = await service.handle({ text: "run qa", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.equal(ok, false);
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /Which pull request/);
});

test("refuses an unregistered repository", async () => {
  const { service, posted, dispatched } = fakes();
  await service.handle({ text: "test acme/other#1", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /not set up for QA/);
});

test("reports a failed dispatch", async () => {
  const { service, posted } = fakes({ dispatchOk: false });
  const ok = await service.handle({ text: "test acme/web#1", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.equal(ok, false);
  assert.match(posted[0].text, /Failed to start the QA pipeline/);
});
