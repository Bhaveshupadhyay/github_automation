/**
 * Cloudflare Worker for Slack Integration with Antigravity Engine (`agy`)
 * Supports Slash Commands, App Mentions, and Interactive Thread Clarifications.
 */

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
      // 1. Handle Slack Slash Commands (application/x-www-form-urlencoded)
      if (contentType.includes("application/x-www-form-urlencoded")) {
        const formData = await request.formData();
        const text = formData.get("text") || "";
        const channelId = formData.get("channel_id") || env.SLACK_CHANNEL_ID;
        const userId = formData.get("user_id") || "";

        if (!text.trim()) {
          return new Response("Usage: `/code [owner/repo] <your prompt>`", { status: 200 });
        }

        ctx.waitUntil(handleSlackCommand(text, channelId, userId, env));

        return new Response("⚡ *Antigravity AI Agent Active!* Initializing execution on GitHub Actions...", {
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
          
          // Ignore bot's own messages to prevent loops
          if (event.bot_id || event.subtype === "bot_message") {
            return new Response("OK", { status: 200 });
          }

          // Case A: Thread Reply Clarification
          if (event.type === "message" && event.thread_ts && event.text) {
            ctx.waitUntil(handleSlackThreadReply(event, env));
            return new Response("OK", { status: 200 });
          }

          // Case B: Direct App Mention (@bot [owner/repo] prompt)
          if (event.type === "app_mention" && event.text) {
            const cleanText = event.text.replace(/<@[A-Z0-9]+>/g, "").trim();
            ctx.waitUntil(handleSlackCommand(cleanText, event.channel, event.user, env, event.ts));
            return new Response("OK", { status: 200 });
          }
        }
      }

      return new Response("Ignored", { status: 200 });
    } catch (err) {
      return new Response(`Worker Error: ${err.message}`, { status: 500 });
    }
  }
};

/**
 * Dispatches GitHub Actions workflow for Slack Commands or App Mentions.
 */
async function handleSlackCommand(text, channelId, userId, env, threadTs = null) {
  const parts = text.trim().split(/\s+/);
  let repo = env.DEFAULT_GITHUB_REPO || "";
  let prompt = text.trim();

  // Strict regex for owner/repo pattern (e.g., bhaveshupadhyay/hiphomboombox_backend)
  const ownerRepoRegex = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

  if (parts.length > 1 && ownerRepoRegex.test(parts[0])) {
    repo = parts[0];
    prompt = parts.slice(1).join(" ");
  }

  if (!repo) {
    console.error("No target repository configured or specified.");
    return;
  }

  // 1. Post initial Slack message to establish thread context
  let slackThreadTs = threadTs;
  if (!slackThreadTs && env.SLACK_BOT_TOKEN) {
    try {
      const postRes = await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.SLACK_BOT_TOKEN}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          channel: channelId,
          text: `🤖 *Antigravity AI Triggered*\n📦 *Repo:* \`${repo}\`\n📌 *Prompt:* \`${prompt}\`\n\n🧠 Initializing Antigravity Engine on GitHub Actions...`
        })
      });
      const postData = await postRes.json();
      if (postData.ok) {
        slackThreadTs = postData.ts;
      }
    } catch (e) {
      console.error("Failed to post initial Slack message:", e);
    }
  }

  // 2. Dispatch GitHub Actions workflow event
  await dispatchGitHubWorkflow(repo, prompt, channelId, slackThreadTs, env);
}

/**
 * Handles Thread Replies when user replies with requested clarification.
 */
async function handleSlackThreadReply(event, env) {
  const channelId = event.channel;
  const threadTs = event.thread_ts;
  const userReply = event.text;

  // Retrieve parent thread message context from Slack
  let parentPrompt = "Previous Coding Request";
  let targetRepo = env.DEFAULT_GITHUB_REPO || "";

  if (env.SLACK_BOT_TOKEN) {
    try {
      const threadRes = await fetch(`https://slack.com/api/conversations.replies?channel=${channelId}&ts=${threadTs}&limit=5`, {
        headers: { "Authorization": `Bearer ${env.SLACK_BOT_TOKEN}` }
      });
      const threadData = await threadRes.json();
      if (threadData.ok && threadData.messages && threadData.messages.length > 0) {
        const parentMsg = threadData.messages[0].text || "";
        const repoMatch = parentMsg.match(/Repo:\*\s*`([^`]+)`/);
        if (repoMatch) {
          targetRepo = repoMatch[1];
        }
        const promptMatch = parentMsg.match(/Prompt:\*\s*`([^`]+)`/);
        if (promptMatch) {
          parentPrompt = promptMatch[1];
        }
      }
    } catch (e) {
      console.error("Failed to fetch Slack thread replies:", e);
    }
  }

  const combinedPrompt = `Original Request: "${parentPrompt}". User Clarification: "${userReply}"`;

  // Inform thread that execution is resuming
  if (env.SLACK_BOT_TOKEN) {
    try {
      await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${env.SLACK_BOT_TOKEN}`,
          "Content-Type": "application/json"
        },
        body: JSON.stringify({
          channel: channelId,
          thread_ts: threadTs,
          text: `⚡ *Clarification Received!* Resuming Antigravity Engine execution with: \`${userReply}\`...`
        })
      });
    } catch (e) {
      console.error("Failed to post resuming Slack message:", e);
    }
  }

  // Dispatch resumed GitHub Action workflow event
  await dispatchGitHubWorkflow(targetRepo, combinedPrompt, channelId, threadTs, env);
}

/**
 * Dispatches repository_dispatch API event to GitHub Actions with timeout and error handling.
 */
async function dispatchGitHubWorkflow(repo, prompt, channelId, threadTs, env) {
  const owner = env.WORKFLOW_REPO_OWNER || "bhaveshupadhyay";
  const repoName = env.WORKFLOW_REPO_NAME || "github_automation";
  const dispatchUrl = `https://api.github.com/repos/${owner}/${repoName}/dispatches`;
  
  try {
    const res = await fetch(dispatchUrl, {
      method: "POST",
      headers: {
        "Authorization": `token ${env.GITHUB_PAT}`,
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Cloudflare-Worker-Antigravity"
      },
      body: JSON.stringify({
        event_type: "ai_developer_task",
        client_payload: {
          target_repo: repo,
          user_prompt: prompt,
          slack_channel: channelId,
          slack_thread_ts: threadTs
        }
      })
    });

    if (!res.ok) {
      const errText = await res.text();
      console.error(`GitHub API dispatch failed (${res.status}): ${errText}`);
    } else {
      console.log(`Successfully dispatched GitHub workflow for target repo: ${repo}`);
    }
  } catch (err) {
    console.error("Error dispatching GitHub workflow:", err);
  }
}
