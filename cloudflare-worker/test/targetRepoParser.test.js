import { test } from "node:test";
import assert from "node:assert/strict";

import { parseTargetRepo } from "../src/services/targetRepoParser.js";

test("a labeled repository is found anywhere in the message and removed from the prompt", () => {
  assert.deepEqual(
    parseTargetRepo("target repo: bhaveshupadhyay/hiphopboombox_web\nadd admin panel to this. it should view, add, update, delete the post."),
    { repo: "bhaveshupadhyay/hiphopboombox_web", prompt: "add admin panel to this. it should view, add, update, delete the post." }
  );
  assert.deepEqual(
    parseTargetRepo("add an admin panel, repo: `acme/web`"),
    { repo: "acme/web", prompt: "add an admin panel," }
  );
  assert.equal(parseTargetRepo("Target Repository acme/web add a footer").repo, "acme/web");
  assert.equal(parseTargetRepo("repository = “acme/web” add a footer").repo, "acme/web");
});

test("a labeled Slack link resolves to its owner/repo", () => {
  assert.deepEqual(
    parseTargetRepo("repo: <https://github.com/acme/web.git|acme/web> add a footer"),
    { repo: "acme/web", prompt: "add a footer" }
  );
});

test("a leading owner/repo keeps working", () => {
  assert.deepEqual(parseTargetRepo("acme/web add an admin panel"), { repo: "acme/web", prompt: "add an admin panel" });
  assert.equal(parseTargetRepo("<https://github.com/acme/web> add a footer").repo, "acme/web");
  assert.deepEqual(parseTargetRepo("acme/web"), { repo: "acme/web", prompt: "" });
});

test("a GitHub link elsewhere names the repository and stays in the prompt", () => {
  const text = "fix the crash in <https://github.com/acme/web/pull/5|this PR>";
  assert.deepEqual(parseTargetRepo(text), { repo: "acme/web", prompt: text });
});

test("prose with slashes, or no repository at all, gives an empty repo", () => {
  assert.equal(parseTargetRepo("and/or add a footer").repo, "");
  assert.equal(parseTargetRepo("update the repo and/or the docs").repo, "");
  assert.equal(parseTargetRepo("add an admin panel").repo, "");
  assert.equal(parseTargetRepo("https://example.com/acme docs are wrong").repo, "");
});
