import { test } from "node:test";
import assert from "node:assert/strict";
import { createHmac } from "node:crypto";

import {
  verifyGithubSignature,
  evaluatePullRequestEvent,
  findTarget,
} from "../src/services/githubWebhookService.js";

const SECRET = "webhook-secret";
const sign = body => "sha256=" + createHmac("sha256", SECRET).update(body).digest("hex");

const REGISTRY = {
  targets: {
    "Acme/Web": { platform: "web", backend_repo: "acme/api", require_label: "qa-preview" },
    "acme/app": { platform: "mobile", backend_repo: "acme/api", require_label: null },
    "acme/default": { platform: "web", backend_repo: "acme/api" },
  },
};

function event({ action = "synchronize", repo = "acme/web", headRepo = repo, labels = ["qa-preview"], label } = {}) {
  return {
    action,
    label: label ? { name: label } : undefined,
    repository: { full_name: repo },
    pull_request: {
      number: 7,
      head: { repo: headRepo ? { full_name: headRepo } : null },
      labels: labels.map(name => ({ name })),
    },
  };
}

test("accepts a correctly signed body", async () => {
  const body = '{"a":1}';
  assert.equal(await verifyGithubSignature(body, sign(body), SECRET), true);
});

test("rejects a tampered body", async () => {
  assert.equal(await verifyGithubSignature('{"a":2}', sign('{"a":1}'), SECRET), false);
});

test("fails closed without a configured secret", async () => {
  const body = "{}";
  assert.equal(await verifyGithubSignature(body, sign(body), undefined), false);
});

test("rejects a missing or malformed signature header", async () => {
  assert.equal(await verifyGithubSignature("{}", null, SECRET), false);
  assert.equal(await verifyGithubSignature("{}", "sha1=abc", SECRET), false);
});

test("registry lookup ignores case, like GitHub", () => {
  assert.equal(findTarget(REGISTRY, "ACME/WEB").platform, "web");
  assert.equal(findTarget(REGISTRY, "acme/none"), null);
});

test("dispatches a labelled push with identifiers only", () => {
  const decision = evaluatePullRequestEvent("pull_request", event(), REGISTRY);
  assert.deepEqual(decision, {
    dispatch: true,
    eventType: "qa_web_preview",
    clientPayload: { repository: "acme/web", pr_number: "7" },
  });
});

test("routes mobile repositories to the mobile pipeline", () => {
  const decision = evaluatePullRequestEvent("pull_request", event({ repo: "acme/app", labels: [] }), REGISTRY);
  assert.equal(decision.eventType, "qa_mobile_preview");
});

test("ignores other events and actions", () => {
  assert.equal(evaluatePullRequestEvent("push", {}, REGISTRY).dispatch, false);
  assert.equal(evaluatePullRequestEvent("pull_request", event({ action: "closed" }), REGISTRY).dispatch, false);
});

test("never dispatches a fork", () => {
  const decision = evaluatePullRequestEvent("pull_request", event({ headRepo: "mallory/web" }), REGISTRY);
  assert.equal(decision.dispatch, false);
  assert.match(decision.reason, /fork/);
});

test("treats a deleted head repository as a fork", () => {
  assert.equal(evaluatePullRequestEvent("pull_request", event({ headRepo: "" }), REGISTRY).dispatch, false);
});

test("ignores unregistered repositories", () => {
  const decision = evaluatePullRequestEvent("pull_request", event({ repo: "acme/other" }), REGISTRY);
  assert.match(decision.reason, /not registered/);
});

test("requires the gate label while piloting", () => {
  const decision = evaluatePullRequestEvent("pull_request", event({ labels: [] }), REGISTRY);
  assert.equal(decision.dispatch, false);
});

test("the gate label defaults to qa-preview when unset", () => {
  assert.equal(evaluatePullRequestEvent("pull_request", event({ repo: "acme/default", labels: [] }), REGISTRY).dispatch, false);
  assert.equal(evaluatePullRequestEvent("pull_request", event({ repo: "acme/default" }), REGISTRY).dispatch, true);
});

test("adding the gate label starts a run; other labels do not", () => {
  assert.equal(
    evaluatePullRequestEvent("pull_request", event({ action: "labeled", label: "qa-preview" }), REGISTRY).dispatch,
    true
  );
  assert.equal(
    evaluatePullRequestEvent("pull_request", event({ action: "labeled", label: "docs", labels: ["qa-preview", "docs"] }), REGISTRY).dispatch,
    false
  );
});

test("without a gate label, label changes do not start runs", () => {
  const decision = evaluatePullRequestEvent("pull_request", event({ repo: "acme/app", action: "labeled", label: "x" }), REGISTRY);
  assert.equal(decision.dispatch, false);
});
