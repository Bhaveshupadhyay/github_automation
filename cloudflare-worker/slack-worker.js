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

const OWNER_REPO_REGEX = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("Slack Antigravity Worker is active!", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    const contentType = request.headers.get("content-type") || "";

    try {
      // Initialize Services (Dependency Injection)
      const llmProvider = createLlmProvider(env);
      const intentService = new IntentService(llmProvider);
      const slackService = new SlackService(env.SLACK_BOT_TOKEN);
      const githubService = new GithubService(
        env.GITHUB_PAT,
        env.WORKFLOW_REPO_OWNER || "bhaveshupadhyay",
        env.WORKFLOW_REPO_NAME || "github_automation"
      );

      // 1. Handle Slack Slash Commands (application/x-www-form-urlencoded)
      if (contentType.includes("application/x-www-form-urlencoded")) {
        const formData = await request.formData();
        const text = formData.get("text") || "";
        const channelId = formData.get("channel_id") || env.SLACK_CHANNEL_ID;
        const userId = formData.get("user_id") || "";

        if (!text.trim()) {
          return new Response("Usage: `/code [owner/repo] <your prompt>`", { status: 200 });
        }

        ctx.waitUntil(handleCommandOrMention(text, channelId, userId, null, env, intentService, slackService, githubService));

        return new Response("⚡ *Antigravity AI Agent Active!* Evaluating intent...", {
          headers: { "Content-Type": "text/plain" }
        });
      }

      // 2. Handle Slack Event Subscriptions (application/json)
      if (contentType.includes("application/json")) {
        const payload = await request.json();

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
            ctx.waitUntil(handleSlackThreadReply(event, env, slackService, githubService));
            return new Response("OK", { status: 200 });
          }

          // Case B: Direct App Mention (@bot [owner/repo] prompt)
          if (event.type === "app_mention" && event.text) {
            const cleanText = event.text.replace(/<@[A-Z0-9]+>/g, "").trim();
            ctx.waitUntil(handleCommandOrMention(cleanText, event.channel, event.user, event.ts, env, intentService, slackService, githubService));
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
async function handleCommandOrMention(text, channelId, userId, threadTs, env, intentService, slackService, githubService) {
  const parts = text.trim().split(/\s+/);
  let repo = env.DEFAULT_GITHUB_REPO || "";
  let prompt = text.trim();

  if (parts.length > 1 && OWNER_REPO_REGEX.test(parts[0])) {
    repo = parts[0];
    prompt = parts.slice(1).join(" ");
  }

  if (!repo) {
    console.error("No target repository configured or specified.");
    await slackService.postMessage(channelId, "⚠️ *Error:* No target repository specified or configured.", threadTs);
    return;
  }

  // Step 1: Fast-Path Intent Evaluation (< 500ms API call)
  const { intent, question } = await intentService.evaluateIntent(repo, prompt);

  let currentThreadTs = threadTs;

  if (intent === IntentType.CLARIFICATION_NEEDED && question) {
    // Fast-path exit: Reply with clarifying question to Slack thread. DO NOT launch GitHub Actions.
    console.log(`[Fast-Path] Clarification requested for repo ${repo}: ${question}`);
    await slackService.postMessage(
      channelId,
      `❓ *Antigravity AI Clarification:* ${question}`,
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

  await githubService.dispatchWorkflow(repo, prompt, channelId, currentThreadTs);
}

/**
 * Handles Thread Replies when user replies with requested clarification.
 */
async function handleSlackThreadReply(event, env, slackService, githubService) {
  const channelId = event.channel;
  const threadTs = event.thread_ts;
  const userReply = event.text;

  // Retrieve parent thread message context from Slack
  const { parentRepo, parentPrompt } = await slackService.fetchThreadParent(channelId, threadTs);
  const targetRepo = parentRepo || env.DEFAULT_GITHUB_REPO || "";
  const combinedPrompt = `Original Request: "${parentPrompt}". User Clarification: "${userReply}"`;

  // Inform thread that execution is resuming
  await slackService.postMessage(
    channelId,
    `⚡ *Clarification Received!* Resuming Antigravity Engine execution with: \`${userReply}\`...`,
    threadTs
  );

  // Dispatch resumed GitHub Action workflow event
  await githubService.dispatchWorkflow(targetRepo, combinedPrompt, channelId, threadTs);
}
