/**
 * Turns GitHub pull request webhooks from registered repositories into QA pipeline
 * dispatches on github_automation. The repositories under test carry no workflow and no
 * secret; this is their only link to the pipeline.
 */

const TRIGGERING_ACTIONS = new Set(["opened", "synchronize", "reopened", "labeled"]);

/**
 * Verifies GitHub's HMAC-SHA256 webhook signature (`X-Hub-Signature-256`).
 * Fails closed: without a configured secret, nothing is accepted, because an accepted
 * webhook runs code with github_automation's secrets.
 * @param {string} rawBody
 * @param {string|null} signatureHeader
 * @param {string|undefined} secret
 * @returns {Promise<boolean>}
 */
export async function verifyGithubSignature(rawBody, signatureHeader, secret) {
  if (!secret || !signatureHeader || !signatureHeader.startsWith("sha256=")) return false;

  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(secret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );
  const signature = await crypto.subtle.sign("HMAC", key, encoder.encode(rawBody));
  const expected = "sha256=" + Array.from(new Uint8Array(signature))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");

  // Constant-time comparison, so response timing reveals nothing about the signature.
  if (expected.length !== signatureHeader.length) return false;
  let diff = 0;
  for (let i = 0; i < expected.length; i++) {
    diff |= expected.charCodeAt(i) ^ signatureHeader.charCodeAt(i);
  }
  return diff === 0;
}

/**
 * Finds a repository in the QA target registry. GitHub treats names case-insensitively.
 * @param {{targets?: Object<string, Object>}} registry
 * @param {string} repository
 */
export function findTarget(registry, repository) {
  const wanted = repository.toLowerCase();
  for (const [name, target] of Object.entries(registry?.targets || {})) {
    if (name.toLowerCase() === wanted) return target;
  }
  return null;
}

/**
 * Decides whether a pull request event should start a QA run.
 * @param {string} eventName  The `X-GitHub-Event` header.
 * @param {Object} payload
 * @param {{targets?: Object<string, Object>}} registry
 * @returns {{dispatch: false, reason: string} | {dispatch: true, eventType: string, clientPayload: Object}}
 */
export function evaluatePullRequestEvent(eventName, payload, registry) {
  if (eventName !== "pull_request") {
    return { dispatch: false, reason: `Ignored ${eventName} event.` };
  }

  const action = payload?.action;
  if (!TRIGGERING_ACTIONS.has(action)) {
    return { dispatch: false, reason: `Ignored pull_request.${action}.` };
  }

  const pr = payload.pull_request || {};
  const repository = payload.repository?.full_name || "";

  // A fork's code would run with github_automation's secrets. The workflow re-checks
  // this against the API, so a forged payload cannot slip one through either.
  const headRepository = pr.head?.repo?.full_name || "";
  if (headRepository.toLowerCase() !== repository.toLowerCase()) {
    return { dispatch: false, reason: `Ignored fork pull request from ${headRepository || "a deleted repository"}.` };
  }

  const target = findTarget(registry, repository);
  if (!target) {
    return { dispatch: false, reason: `${repository} is not registered in contracts/qa-targets.json.` };
  }

  // `require_label` defaults to the pilot label; an explicit null previews every PR.
  const requiredLabel = target.require_label === undefined ? "qa-preview" : target.require_label;
  if (requiredLabel) {
    const labels = (pr.labels || []).map(label => label.name);
    if (!labels.includes(requiredLabel)) {
      return { dispatch: false, reason: `Pull request lacks the '${requiredLabel}' label.` };
    }
    // Adding an unrelated label changes no code; only the gate label starts a run.
    if (action === "labeled" && payload.label?.name !== requiredLabel) {
      return { dispatch: false, reason: `Ignored unrelated label '${payload.label?.name}'.` };
    }
  } else if (action === "labeled") {
    return { dispatch: false, reason: "Ignored label change; every pull request is previewed on push." };
  }

  return {
    dispatch: true,
    eventType: `qa_${target.platform}_preview`,
    // Only identifiers: the workflow reads everything else fresh from the API.
    clientPayload: { repository, pr_number: String(pr.number) },
  };
}
