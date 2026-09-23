/**
 * Starts the QA pipeline on github_automation when a user tags the bot and asks for a
 * pull request to be tested. QA never runs on its own: no webhook, no push trigger.
 */

// A full PR link, as the bot posts it: https://github.com/owner/repo/pull/12
const PR_URL_PATTERN = /github\.com\/([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)\/pull\/(\d+)/g;
// The short form a person types: owner/repo#12
const PR_SHORT_PATTERN = /(?:^|[\s(<`])([A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+)#(\d+)\b/;

/**
 * Finds a pull request named in a message, as a link or as owner/repo#N.
 * @param {string} text
 * @returns {{repository: string, number: number} | null}
 */
export function extractPullRequestRef(text) {
  if (!text) return null;
  const url = [...text.matchAll(PR_URL_PATTERN)][0];
  if (url) return { repository: url[1], number: Number(url[2]) };
  const short = text.match(PR_SHORT_PATTERN);
  if (short) return { repository: short[1], number: Number(short[2]) };
  return null;
}

/**
 * Finds the most recent pull request linked in a Slack thread — normally the one the
 * bot opened for this thread's coding request.
 * @param {Array<{text?: string}>} messages  Oldest first, as conversations.replies returns them.
 * @returns {{repository: string, number: number} | null}
 */
export function findLatestPullRequestInThread(messages) {
  for (let i = (messages || []).length - 1; i >= 0; i--) {
    const matches = [...(messages[i].text || "").matchAll(PR_URL_PATTERN)];
    if (matches.length) {
      const last = matches[matches.length - 1];
      return { repository: last[1], number: Number(last[2]) };
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
   * Resolves which pull request to test and dispatches the pipeline for it.
   * @param {Object} request
   * @param {string} request.text         The user's message.
   * @param {string} request.channelId
   * @param {string|null} request.threadTs  The thread the message was posted in, if any.
   * @param {string} request.replyTs      Where the bot answers: the thread, or the message itself.
   * @returns {Promise<boolean>} Whether a run was dispatched.
   */
  async handle({ text, channelId, threadTs, replyTs }) {
    let pr = extractPullRequestRef(text);
    if (!pr && threadTs) {
      const messages = await this.slackService.fetchThreadMessages(channelId, threadTs);
      pr = findLatestPullRequestInThread(messages);
    }

    if (!pr) {
      await this.slackService.postMessage(
        channelId,
        "❓ *Which pull request should I test?* Send its link, or `owner/repo#number`, " +
        "or ask me in the thread where I opened it.",
        replyTs
      );
      return false;
    }

    const prLabel = `${pr.repository}#${pr.number}`;
    const registry = await this.registryService.getRegistry();
    const target = findTarget(registry, pr.repository);
    if (!target) {
      await this.slackService.postMessage(
        channelId,
        `⚠️ \`${pr.repository}\` is not set up for QA testing. Add it to \`contracts/qa-targets.json\` in github_automation.`,
        replyTs
      );
      return false;
    }

    const dispatched = await this.githubService.dispatchEvent(`qa_${target.platform}_preview`, {
      repository: pr.repository,
      pr_number: String(pr.number),
      slack_channel: channelId,
      slack_thread_ts: replyTs
    });

    await this.slackService.postMessage(
      channelId,
      dispatched
        ? `🧪 *QA testing started* for \`${prLabel}\` on its PR branch.\n` +
          "Generating test cases from the diff, running them and recording the session. " +
          "Results will be posted here and on the pull request."
        : "❌ *Error:* Failed to start the QA pipeline. Check the worker logs or GITHUB_PAT configuration.",
      replyTs
    );
    return dispatched;
  }
}
