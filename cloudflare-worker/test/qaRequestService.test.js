import { test } from "node:test";
import assert from "node:assert/strict";

import {
  extractPullRequestRefs,
  findLatestPullRequestInThread,
  findTarget,
  parseBackendAnswer,
  QaRequestService,
} from "../src/services/qaRequestService.js";

const REGISTRY = {
  targets: {
    "Acme/Web": { platform: "web", backend_repo: "acme/api", dev_api_url: "https://dev.acme.test" },
    "acme/app": { platform: "mobile", backend_repo: "acme/api" },
  },
};

const QUESTION = { bot_id: "B1", ts: "200.0", text: "🧪 *QA for* `acme/web#9` — *which backend should it run against?* Reply with:\n• …" };

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

test("reads PR links as Slack renders them, and the owner/repo#N form", () => {
  assert.deepEqual(
    extractPullRequestRefs("test <https://github.com/acme/web/pull/12|this> with acme/api#3"),
    [{ repository: "acme/web", number: 12 }, { repository: "acme/api", number: 3 }]
  );
  assert.deepEqual(extractPullRequestRefs("please run qa"), []);
});

test("thread lookup takes the latest PR that passes the filter", () => {
  const messages = [
    { text: "🔗 *PR Link:* <https://github.com/acme/web/pull/3|View Pull Request>" },
    { text: "backend: <https://github.com/acme/api/pull/8>" },
  ];
  assert.deepEqual(findLatestPullRequestInThread(messages), { repository: "acme/api", number: 8 });
  const frontendOnly = ref => ref.repository === "acme/web";
  assert.deepEqual(findLatestPullRequestInThread(messages, frontendOnly), { repository: "acme/web", number: 3 });
});

test("registry lookup ignores case, like GitHub", () => {
  assert.equal(findTarget(REGISTRY, "ACME/WEB").platform, "web");
  assert.equal(findTarget(REGISTRY, "acme/none"), null);
});

test("backend answers", () => {
  assert.equal(parseBackendAnswer("<https://github.com/acme/api/pull/4>", "acme/web"), "acme/api#4");
  assert.equal(parseBackendAnswer("<@UBOT> acme/api#4", "acme/web"), "acme/api#4");
  assert.equal(parseBackendAnswer("use dev", "acme/web"), "dev");
  assert.equal(parseBackendAnswer("main", "acme/web"), "main");
  assert.equal(parseBackendAnswer("main of acme/other-api", "acme/web"), "main:acme/other-api");
  assert.equal(parseBackendAnswer("no backend pr", "acme/web"), "none");
  assert.equal(parseBackendAnswer("hmm?", "acme/web"), null);
  // A repository containing `dev` is a repository, not the dev APIs.
  assert.equal(parseBackendAnswer("main of acme/dev-api", "acme/web"), "main:acme/dev-api");
  assert.equal(parseBackendAnswer("main acme/api-dev", "acme/web"), "main:acme/api-dev");
  assert.equal(parseBackendAnswer("dev please", "acme/web"), "dev");
  // A link to the frontend PR itself is not a backend.
  assert.equal(parseBackendAnswer("acme/web#9", "acme/web"), null);
});

test("a QA request asks which backend before dispatching anything", async () => {
  const { service, posted, dispatched } = fakes({
    threadMessages: [{ text: "🔗 *PR Link:* <https://github.com/acme/web/pull/9|View Pull Request>" }],
  });
  const ok = await service.handle({ text: "run qa on it", channelId: "C1", threadTs: "100.1", replyTs: "100.1" });
  assert.equal(ok, false);
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /QA for\* `acme\/web#9` — \*which backend/);
  assert.match(posted[0].text, /dev\.acme\.test/);
  assert.equal(posted[0].ts, "100.1");
});

test("a request naming the backend PR too dispatches at once", async () => {
  const { service, dispatched } = fakes();
  await service.handle({ text: "test acme/web#9 against acme/api#4", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.deepEqual(dispatched[0], {
    eventType: "qa_web_preview",
    payload: { repository: "acme/web", pr_number: "9", backend: "acme/api#4", slack_channel: "C1", slack_thread_ts: "5.5" },
  });
});

test("asks which PR when none can be found", async () => {
  const { service, posted, dispatched } = fakes();
  await service.handle({ text: "run qa", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /Which pull request/);
});

test("refuses an unregistered repository", async () => {
  const { service, posted, dispatched } = fakes();
  await service.handle({ text: "test acme/other#1", channelId: "C1", threadTs: null, replyTs: "5.5" });
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /not set up for QA/);
});

test("a backend PR answer dispatches against that PR", async () => {
  const { service, posted, dispatched } = fakes({ threadMessages: [QUESTION] });
  const handled = await service.handleBackendAnswer({
    text: "<https://github.com/acme/api/pull/4>", channelId: "C1", threadTs: "100.1", messageTs: "201.0",
  });
  assert.equal(handled, true);
  assert.equal(dispatched[0].payload.backend, "acme/api#4");
  assert.equal(dispatched[0].payload.pr_number, "9");
  assert.match(posted[0].text, /against backend PR `acme\/api#4`/);
});

test("`dev` and `main` answers dispatch with that choice", async () => {
  for (const [answer, backend, said] of [["dev", "dev", /dev APIs/], ["main", "main", /`acme\/api` main/]]) {
    const { service, posted, dispatched } = fakes({ threadMessages: [QUESTION] });
    await service.handleBackendAnswer({ text: answer, channelId: "C1", threadTs: "100.1", messageTs: "201.0" });
    assert.equal(dispatched[0].payload.backend, backend);
    assert.match(posted[0].text, said);
  }
});

test("'no backend PR' is answered with the dev and main options", async () => {
  const { service, posted, dispatched } = fakes({ threadMessages: [QUESTION] });
  await service.handleBackendAnswer({ text: "there isn't one", channelId: "C1", threadTs: "100.1", messageTs: "201.0" });
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /`main`/);
  assert.match(posted[0].text, /`dev`/);
  assert.doesNotMatch(posted[0].text, /backend PR link/);
});

test("an unrecognised answer asks again", async () => {
  const { service, posted, dispatched } = fakes({ threadMessages: [QUESTION] });
  assert.equal(await service.handleBackendAnswer({ text: "hmm", channelId: "C1", threadTs: "100.1", messageTs: "201.0" }), true);
  assert.equal(dispatched.length, 0);
  assert.match(posted[0].text, /which backend/);
});

test("a message older than the question is not its answer", async () => {
  // Slack delivers the request that prompted the question a second time.
  const { service, dispatched } = fakes({ threadMessages: [QUESTION] });
  assert.equal(await service.handleBackendAnswer({ text: "run qa", channelId: "C1", threadTs: "100.1", messageTs: "199.0" }), false);
  assert.equal(dispatched.length, 0);
});

test("once the bot has moved on, a reply is not an answer", async () => {
  const { service } = fakes({ threadMessages: [QUESTION, { bot_id: "B1", ts: "202.0", text: "🧪 *QA testing started*" }] });
  assert.equal(await service.handleBackendAnswer({ text: "dev", channelId: "C1", threadTs: "100.1", messageTs: "203.0" }), false);
});
