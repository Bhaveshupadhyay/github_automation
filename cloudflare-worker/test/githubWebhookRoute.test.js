import { test, afterEach } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import worker from "../slack-worker.js";

const SECRET = "webhook-secret";
const ENV = {
  GITHUB_WEBHOOK_SECRET: SECRET,
  GITHUB_PAT: "pat",
  WORKFLOW_REPO_OWNER: "bhaveshupadhyay",
  WORKFLOW_REPO_NAME: "github_automation",
};
const REGISTRY = { targets: { "acme/web": { platform: "web", backend_repo: "acme/api" } } };
const realFetch = globalThis.fetch;

afterEach(() => {
  globalThis.fetch = realFetch;
});

function webhook(eventName, payload, { signature } = {}) {
  const body = JSON.stringify(payload);
  return new Request("https://worker.example/", {
    method: "POST",
    headers: {
      "content-type": "application/json",
      "x-github-event": eventName,
      "x-hub-signature-256": signature ?? "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex"),
    },
    body,
  });
}

function mockGithub() {
  const calls = [];
  globalThis.fetch = async (url, init = {}) => {
    calls.push({ url: String(url), init });
    if (String(url).includes("/contents/contracts/qa-targets.json")) {
      return new Response(JSON.stringify(REGISTRY), { status: 200 });
    }
    if (String(url).endsWith("/dispatches")) {
      return new Response(null, { status: 204 });
    }
    return new Response("unexpected", { status: 500 });
  };
  return calls;
}

const labelledPush = {
  action: "synchronize",
  repository: { full_name: "acme/web" },
  pull_request: { number: 7, head: { repo: { full_name: "acme/web" } }, labels: [{ name: "qa-preview" }] },
};

test("a signed, labelled push dispatches the web pipeline on github_automation", async () => {
  const calls = mockGithub();
  const res = await worker.fetch(webhook("pull_request", labelledPush), ENV, { waitUntil() {} });
  assert.equal(res.status, 202);
  const dispatch = calls.find(c => c.url.endsWith("/dispatches"));
  assert.equal(dispatch.url, "https://api.github.com/repos/bhaveshupadhyay/github_automation/dispatches");
  assert.deepEqual(JSON.parse(dispatch.init.body), {
    event_type: "qa_web_preview",
    client_payload: { repository: "acme/web", pr_number: "7" },
  });
});

test("an unsigned webhook is rejected before GitHub is contacted", async () => {
  const calls = mockGithub();
  const res = await worker.fetch(webhook("pull_request", labelledPush, { signature: "sha256=00" }), ENV, {});
  assert.equal(res.status, 401);
  assert.equal(calls.length, 0);
});

test("ping is answered", async () => {
  mockGithub();
  const res = await worker.fetch(webhook("ping", { zen: "hi" }), ENV, {});
  assert.equal(res.status, 200);
});

test("an unlabelled push is acknowledged without dispatching", async () => {
  const calls = mockGithub();
  const payload = { ...labelledPush, pull_request: { ...labelledPush.pull_request, labels: [] } };
  const res = await worker.fetch(webhook("pull_request", payload), ENV, {});
  assert.equal(res.status, 200);
  assert.equal(calls.some(c => c.url.endsWith("/dispatches")), false);
});
