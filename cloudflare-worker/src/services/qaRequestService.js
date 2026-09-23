/**
 * Starts the QA pipeline on github_automation when a user tags the bot and asks for a
 * pull request to be tested. QA never runs on its own: no webhook, no push trigger.
 */

// A full PR link, as the bot posts it: https://github.com/owner/repo/pull/12
const PR_URL_PATTERN = /github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/pull\/(\d+)/g;
// The short form a person types: owner/repo#12
const PR_SHORT_PATTERN = /(?:^|[\s(<`])([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)\b/;

/**
 * Every pull request named in a message, in order.
 * @param {string} text
 * @returns {Array<{repository: string, number: number}>}
 */
export function extractPullRequestRefs(text) {
  if (!text) return [];
  const refs = [...text.matchAll(PR_URL_PATTERN)].map(m => ({ repository: m[1], number: Number(m[2]) }));
  for (const m of text.matchAll(new RegExp(PR_SHORT_PATTERN.source, "g"))) {
    refs.push({ repository: m[1], number: Number(m[2]) });
  }
  return refs;
}

// The bot's question, and how it names the frontend PR it is asking about.
const QUESTION_PATTERN = /QA for\* `([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)`.*which backend/s;
const MAIN_PATTERN = /\bmain\b(?:\s+(?:of\s+)?`?([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)`?)?/i;

/**
 * Reads the requester's answer to "which backend?" as a backend spec.
 * @param {string} text
 * @param {string} frontendRepository  A PR in this repository is not a backend PR.
 * @returns {string|null} `owner/repo#N`, `dev`, `main`, `main:owner/repo`, `none`, or null if unrecognised.
 */
export function parseBackendAnswer(text, frontendRepository) {
  const clean = (text || "").replace(/<@[A-Z0-9]+>/g, " ");
  const backendPr = extractPullRequestRefs(clean)
    .find(ref => ref.repository.toLowerCase() !== frontendRepository.toLowerCase());
  if (backendPr) return `${backendPr.repository}#${backendPr.number}`;
  if (/\bdev\b/i.test(clean)) return "dev";
  const main = clean.match(MAIN_PATTERN);
  if (main) return main[1] ? `main:${main[1]}` : "main";
  if (/\b(no|none|nope|there isn'?t)\b/i.test(clean)) return "none";
  return null;
}

/**
 * Finds the most recent pull request linked in a Slack thread — normally the one the
 * bot opened for this thread's coding request.
 * @param {Array<{text?: string}>} messages  Oldest first, as conversations.replies returns them.
 * @returns {{repository: string, number: number} | null}
 */
export function findLatestPullRequestInThread(messages, accept = () => true) {
  for (let i = (messages || []).length - 1; i >= 0; i--) {
    const matches = [...(messages[i].text || "").matchAll(PR_URL_PATTERN)].reverse();
    for (const match of matches) {
      const ref = { repository: match[1], number: Number(match[2]) };
      if (accept(ref)) return ref;
    }
  }
  return null;
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

export class QaRequestService {
  /**
   * @param {import("./slackService.js").SlackService} slackService
   * @param {import("./githubService.js").GithubService} githubService
   * @param {import("./qaTargetRegistryService.js").QaTargetRegistryService} registryService
   */
  constructor(slackService, githubService, registryService) {
    this.slackService = slackService;
    this.githubService = githubService;
    this.registryService = registryService;
  }

  /**
   * A tagged QA request. Finds the frontend PR, then asks which backend to test against
   * unless the message already names a backend PR.
   * @param {Object} request
   * @param {string} request.text         The user's message.
   * @param {string} request.channelId
   * @param {string|null} request.threadTs  The thread the message was posted in, if any.
   * @param {string} request.replyTs      Where the bot answers: the thread, or the message itself.
   * @returns {Promise<boolean>} Whether a run was dispatched.
   */
  async handle({ text, channelId, threadTs, replyTs }) {
    const registry = await this.registryService.getRegistry();
    const isRegistered = ref => Boolean(findTarget(registry, ref.repository));

    const named = extractPullRequestRefs(text);
    let frontend = named.find(isRegistered) || null;
    if (!frontend && threadTs) {
      const messages = await this.slackService.fetchThreadMessages(channelId, threadTs);
      frontend = findLatestPullRequestInThread(messages, isRegistered);
    }

    if (!frontend) {
      const unregistered = named[0];
      await this.slackService.postMessage(
        channelId,
        unregistered
          ? `⚠️ \`${unregistered.repository}\` is not set up for QA testing. Add it to \`contracts/qa-targets.json\` in github_automation.`
          : "❓ *Which pull request should I test?* Send its link, or `owner/repo#number`, " +
            "or ask me in the thread where I opened it.",
        replyTs
      );
      return false;
    }

    const target = findTarget(registry, frontend.repository);
    const backendPr = named.find(ref => ref.repository.toLowerCase() !== frontend.repository.toLowerCase());
    if (backendPr) {
      return this.dispatch(frontend, target, `${backendPr.repository}#${backendPr.number}`, channelId, replyTs);
    }

    await this.askForBackend(frontend, target, channelId, replyTs);
    return false;
  }

  /**
   * A reply in a thread where the bot is waiting to hear which backend to use.
   * @returns {Promise<boolean>} Whether the reply was an answer to that question.
   */
  async handleBackendAnswer({ text, channelId, threadTs, messageTs }) {
    const question = await this.pendingQuestion(channelId, threadTs, messageTs);
    if (!question) return false;

    const registry = await this.registryService.getRegistry();
    const target = findTarget(registry, question.repository);
    if (!target) return false;

    const answer = parseBackendAnswer(text, question.repository);
    if (answer === null || answer === "none") {
      await this.askForBackend(question, target, channelId, threadTs, answer === "none");
      return true;
    }
    await this.dispatch(question, target, answer, channelId, threadTs);
    return true;
  }

  /**
   * The frontend PR the bot is waiting on a backend for: its question is the bot's
   * latest message in the thread, and the message at `messageTs` came after it. The
   * request that prompted the question is delivered twice by Slack, and the later copy
   * must not be read as its own answer.
   * @returns {Promise<{repository: string, number: number} | null>}
   */
  async pendingQuestion(channelId, threadTs, messageTs) {
    if (!threadTs) return null;
    const messages = await this.slackService.fetchThreadMessages(channelId, threadTs);
    const lastBotMessage = [...messages].reverse().find(message => message.bot_id);
    const match = lastBotMessage?.text?.match(QUESTION_PATTERN);
    if (!match || Number(messageTs) <= Number(lastBotMessage.ts)) return null;
    return { repository: match[1], number: Number(match[2]) };
  }

  async askForBackend(frontend, target, channelId, replyTs, noBackendPr = false) {
    const dev = target.dev_api_url
      ? `\`dev\` — use the deployed dev APIs (${target.dev_api_url}); no backend is started`
      : "`dev` — use the deployed dev APIs _(not configured yet: set `dev_api_url` in contracts/qa-targets.json)_";
    const options = noBackendPr
      ? [
          `\`main\` — run \`${target.backend_repo}\`'s main branch in the runner (or \`main owner/repo\` for another backend)`,
          dev,
        ]
      : [
          "the backend PR link, or `owner/repo#number` — test against that PR's branch",
          `\`main\` — no backend PR: run \`${target.backend_repo}\`'s main branch in the runner (or \`main owner/repo\`)`,
          dev,
        ];
    await this.slackService.postMessage(
      channelId,
      `🧪 *QA for* \`${frontend.repository}#${frontend.number}\` — *which backend should it run against?* Reply with:\n` +
        options.map(option => `• ${option}`).join("\n"),
      replyTs
    );
  }

  async dispatch(frontend, target, backend, channelId, replyTs) {
    const dispatched = await this.githubService.dispatchEvent(`qa_${target.platform}_preview`, {
      repository: frontend.repository,
      pr_number: String(frontend.number),
      backend,
      slack_channel: channelId,
      slack_thread_ts: replyTs
    });

    const against = backend === "dev"
      ? "the deployed dev APIs"
      : backend.startsWith("main")
        ? `\`${backend === "main" ? target.backend_repo : backend.slice("main:".length)}\` main`
        : `backend PR \`${backend}\``;
    await this.slackService.postMessage(
      channelId,
      dispatched
        ? `🧪 *QA testing started* for \`${frontend.repository}#${frontend.number}\` (its PR branch) against ${against}.\n` +
          "Generating test cases from the diff, running them and recording the session. " +
          "Results will be posted here and on the pull request."
        : "❌ *Error:* Failed to start the QA pipeline. Check the worker logs or GITHUB_PAT configuration.",
      replyTs
    );
    return dispatched;
  }
}
