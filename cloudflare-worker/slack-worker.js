/**
 * Cloudflare Worker for Slack Integration with Antigravity Engine (`agy`)
 * Supports Slash Commands, App Mentions, Fast-Path LLM Intent Routing, and Thread Clarifications.
 * Built with Clean Architecture & Pluggable LLM Strategy Pattern.
 */

import { IntentType } from "./src/types/intentTypes.js";
import { createLlmProvider } from "./src/providers/llmFactory.js";
import { IntentService } from "./src/services/intentService.js";
import { SlackService } from "./src/services/slackService.js";
import { GithubService } from "./src/services/githubService.js";
import { QaTargetRegistryService } from "./src/services/qaTargetRegistryService.js";
import { QaRequestService } from "./src/services/qaRequestService.js";
import { parseTargetRepo } from "./src/services/targetRepoParser.js";

const REPO_QUESTION =
  "❓ *Antigravity AI Clarification:* Which repository should I work in? Reply in this thread with `owner/repo`.";

/**
 * Verifies Slack HMAC-SHA256 request signature.
 */
async function verifySlackSignature(request, rawBody, signingSecret) {
  if (!signingSecret) return true; // Skip if signing secret not set in env

  const timestamp = request.headers.get("x-slack-request-timestamp");
  const slackSignature = request.headers.get("x-slack-signature");

  if (!timestamp || !slackSignature) return false;

  const now = Math.floor(Date.now() / 1000);
  if (Math.abs(now - parseInt(timestamp, 10)) > 300) {
    return false; // Request older than 5 minutes
  }

  const sigBaseString = `v0:${timestamp}:${rawBody}`;
  const encoder = new TextEncoder();
  const key = await crypto.subtle.importKey(
    "raw",
    encoder.encode(signingSecret),
    { name: "HMAC", hash: "SHA-256" },
    false,
    ["sign"]
  );

  const signature = await crypto.subtle.sign(
    "HMAC",
    key,
    encoder.encode(sigBaseString)
  );

  const hashHex = "v0=" + Array.from(new Uint8Array(signature))
    .map(b => b.toString(16).padStart(2, "0"))
    .join("");

  return hashHex === slackSignature;
}

// Shared across requests within an isolate, so the registry cache survives between messages.
let qaTargetRegistryService = null;

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("Slack Antigravity Worker is active!", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const rawBody = await request.text();

    // Verify Slack Request Signature
    const isValid = await verifySlackSignature(request, rawBody, env.SLACK_SIGNING_SECRET);
    if (!isValid) {
      console.warn("Unauthorized request: Slack signature verification failed.");
      return new Response("Unauthorized", { status: 401 });
    }

    const contentType = request.headers.get("content-type") || "";

    try {
      // Initialize Services (Dependency Injection)
      const llmProvider = createLlmProvider(env);
      const intentService = new IntentService(llmProvider);
      const slackService = new SlackService(env.SLACK_BOT_TOKEN);
      const githubService = new GithubService(
        env.GITHUB_PAT,
        env.WORKFLOW_REPO_OWNER,
        env.WORKFLOW_REPO_NAME
      );
      qaTargetRegistryService ??= new QaTargetRegistryService(
        env.GITHUB_PAT,
        env.WORKFLOW_REPO_OWNER,
        env.WORKFLOW_REPO_NAME
      );
      const qaRequestService = new QaRequestService(slackService, githubService, qaTargetRegistryService);

      // 1. Handle Slack Slash Commands (application/x-www-form-urlencoded)
      if (contentType.includes("application/x-www-form-urlencoded")) {
        const formData = new URLSearchParams(rawBody);
        const text = formData.get("text") || "";
        const channelId = formData.get("channel_id") || env.SLACK_CHANNEL_ID;
        const userId = formData.get("user_id") || "";

        if (!text.trim()) {
          return new Response("Usage: `/code [owner/repo] <your prompt>`", { status: 200 });
        }

        ctx.waitUntil(handleCommandOrMention(text, channelId, userId, null, null, env, intentService, slackService, githubService, qaRequestService));

        return new Response("⚡ *Antigravity AI Agent Active!* Evaluating intent...", {
          headers: { "Content-Type": "text/plain" }
        });
      }

      // 2. Handle Slack Event Subscriptions (application/json)
      if (contentType.includes("application/json")) {
        const payload = JSON.parse(rawBody);

        // Handle Slack URL Verification Challenge
        if (payload.type === "url_verification") {
          return new Response(JSON.stringify({ challenge: payload.challenge }), {
            headers: { "Content-Type": "application/json" },
            status: 200
          });
        }

        // Handle Event Callback (App Mentions & Thread Replies)
        if (payload.type === "event_callback" && payload.event) {
          const event = payload.event;
          
          // Ignore bot's own messages to prevent infinite loops
          if (event.bot_id || event.subtype === "bot_message") {
            return new Response("OK", { status: 200 });
          }

          // Case A: Thread Reply Clarification
          if (event.type === "message" && event.thread_ts && event.text) {
            ctx.waitUntil(handleSlackThreadReply(event, env, intentService, slackService, githubService, qaRequestService));
            return new Response("OK", { status: 200 });
          }

          // Case B: Direct App Mention (@bot [owner/repo] prompt)
          if (event.type === "app_mention" && event.text) {
            const cleanText = event.text.replace(/<@[A-Z0-9]+>/g, "").trim();
            ctx.waitUntil(handleCommandOrMention(cleanText, event.channel, event.user, event.ts, event.thread_ts || null, env, intentService, slackService, githubService, qaRequestService));
            return new Response("OK", { status: 200 });
          }
        }
      }

      return new Response("Ignored", { status: 200 });
    } catch (err) {
      console.error("Worker Execution Error:", err);
      return new Response(`Worker Error: ${err.message}`, { status: 500 });
    }
  }
};

/**
 * Handles incoming user commands or app mentions with Fast-Path Intent Routing.
 */
async function handleCommandOrMention(text, channelId, userId, threadTs, parentThreadTs, env, intentService, slackService, githubService, qaRequestService) {
  const { repo, prompt } = parseTargetRepo(text);

  // A tagged answer to the bot's backend question is handled by the thread-reply path.
  if (await qaRequestService.pendingQuestion(channelId, parentThreadTs, threadTs)) {
    return;
  }

  // Step 1: Fast-Path Intent Evaluation (< 500ms API call)
  const { intent, question } = await intentService.evaluateIntent(repo, prompt);

  // QA testing runs only when asked for, and tests an existing pull request's branch.
  if (intent === IntentType.QA_TESTING) {
    await qaRequestService.handle({
      text,
      channelId,
      threadTs: parentThreadTs,
      replyTs: parentThreadTs || threadTs
    });
    return;
  }

  // A tagged reply in a request's thread is also delivered as a thread message, and that
  // path resumes the request; handling it here too would start a second run.
  if (parentThreadTs) {
    const { parentRepo, parentPrompt } = await slackService.fetchThreadParent(channelId, parentThreadTs);
    if (parentRepo || parentPrompt) {
      return;
    }
  }

  let currentThreadTs = threadTs;

  // The thread-reply path resumes from the Repo and Prompt markers in this header, so it is
  // posted into the thread even when the request itself starts the thread.
  const postRequestHeader = async () => {
    const repoLine = repo ? `\n📦 *Repo:* \`${repo}\`` : "";
    const ts = await slackService.postMessage(
      channelId,
      `🤖 *Antigravity AI Request Received*${repoLine}\n📌 *Prompt:* \`${prompt}\``,
      currentThreadTs
    );
    currentThreadTs ||= ts;
  };

  // No default repository: ask for one. The header then carries only the prompt, and the
  // thread-reply path takes the repository from the answer.
  if (!repo) {
    await postRequestHeader();
    await slackService.postMessage(channelId, REPO_QUESTION, currentThreadTs);
    return;
  }

  const clarification = prompt
    ? intent === IntentType.CLARIFICATION_NEEDED && question
    : `What should I change in \`${repo}\`?`;

  if (clarification) {
    console.log(`[Fast-Path] Clarification requested for repo ${repo}: ${clarification}`);
    await postRequestHeader();
    await slackService.postMessage(
      channelId,
      `❓ *Antigravity AI Clarification:* ${clarification}`,
      currentThreadTs
    );
    return;
  }

  // Step 2: Intent is CODE_DEVELOPMENT -> Post status and trigger GitHub Action execution
  if (!currentThreadTs) {
    currentThreadTs = await slackService.postMessage(
      channelId,
      `🤖 *Antigravity AI Triggered*\n📦 *Repo:* \`${repo}\`\n📌 *Prompt:* \`${prompt}\`\n\n🧠 Initializing Antigravity Engine on GitHub Actions...`
    );
  }

  const dispatched = await githubService.dispatchWorkflow(repo, prompt, channelId, currentThreadTs);
  if (!dispatched) {
    await slackService.postMessage(
      channelId,
      "❌ *Error:* Failed to start the GitHub Actions workflow. Check the worker logs or GITHUB_PAT configuration.",
      currentThreadTs
    );
  }
}

/**
 * Handles Thread Replies when user replies with requested clarification.
 */
async function handleSlackThreadReply(event, env, intentService, slackService, githubService, qaRequestService) {
  const channelId = event.channel;
  const threadTs = event.thread_ts;
  const userReply = event.text;

  // An answer to "which backend should QA run against?", tagged or not. Handled here
  // only, since Slack also delivers a tagged reply as an app_mention.
  if (await qaRequestService.handleBackendAnswer({ text: userReply, channelId, threadTs, messageTs: event.ts })) {
    return;
  }

  // Retrieve parent thread message context from Slack
  const { parentRepo, parentPrompt } = await slackService.fetchThreadParent(channelId, threadTs);
  
  // Strict check: Ignore non-bot thread replies that don't match an Antigravity AI thread
  if (!parentRepo && !parentPrompt) {
    return;
  }

  const targetRepo = parentRepo || parseTargetRepo(userReply.replace(/<@[A-Z0-9]+>/g, "")).repo;

  // A QA request is not a coding clarification. QA starts only when the bot is tagged,
  // which the app_mention path handles; resuming the coding run here would change code.
  const { intent } = await intentService.evaluateIntent(targetRepo, userReply);
  if (intent === IntentType.QA_TESTING) {
    return;
  }
  if (!targetRepo) {
    await slackService.postMessage(channelId, REPO_QUESTION, threadTs);
    return;
  }

  const combinedPrompt = `Original Request: "${parentPrompt}". User Clarification: "${userReply}"`;

  // Inform thread that execution is resuming
  await slackService.postMessage(
    channelId,
    `⚡ *Clarification Received!* Resuming Antigravity Engine execution with: \`${userReply}\`...\n📦 *Repo:* \`${targetRepo}\``,
    threadTs
  );

  // Dispatch resumed GitHub Action workflow event
  const dispatched = await githubService.dispatchWorkflow(targetRepo, combinedPrompt, channelId, threadTs);
  if (!dispatched) {
    await slackService.postMessage(
      channelId,
      "❌ *Error:* Failed to dispatch resumed workflow to GitHub Actions.",
      threadTs
    );
  }
}

