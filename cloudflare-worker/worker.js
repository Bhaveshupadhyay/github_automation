/**
 * Cloudflare Worker for Telegram Integration with Antigravity Engine (`agy`)
 * Supports Telegram Bot Webhooks with dynamic repository routing.
 */

export default {
  async fetch(request, env, ctx) {
    if (request.method === "GET") {
      return new Response("Telegram Antigravity Worker active!", { status: 200 });
    }

    if (request.method !== "POST") {
      return new Response("Method not allowed", { status: 405 });
    }

    try {
      const update = await request.json();

      if (update.message && update.message.text) {
        const chatId = update.message.chat.id.toString();
        const text = update.message.text;

        // Optional Chat ID Whitelisting
        if (env.ALLOWED_CHAT_ID && env.ALLOWED_CHAT_ID !== chatId) {
          console.warn(`Unauthorized chat attempt: ${chatId}`);
          return new Response("Forbidden", { status: 403 });
        }

        ctx.waitUntil(handleTelegramCommand(text, chatId, env));
      }

      return new Response("OK", { status: 200 });
    } catch (err) {
      return new Response(`Worker Error: ${err.message}`, { status: 500 });
    }
  }
};

async function handleTelegramCommand(text, chatId, env) {
  let prompt = text.replace(/^\/code\s*/, "").trim();
  let repo = env.DEFAULT_GITHUB_REPO || "";

  const ownerRepoRegex = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;
  const parts = prompt.split(/\s+/);

  if (parts.length > 1 && ownerRepoRegex.test(parts[0])) {
    repo = parts[0];
    prompt = parts.slice(1).join(" ");
  }

  // 1. Send Telegram Acknowledgment Message
  if (env.TELEGRAM_BOT_TOKEN) {
    await sendTelegramMessage(chatId, `⚡ *Antigravity AI Agent Active!*\n\n📦 *Repo:* \`${escapeMarkdownV2(repo)}\`\n📌 *Prompt:* \`${escapeMarkdownV2(prompt)}\`\n\n🧠 Initializing execution on GitHub Actions...`, env);
  }

  // 2. Dispatch GitHub Actions Workflow
  const owner = env.WORKFLOW_REPO_OWNER || "bhaveshupadhyay";
  const repoName = env.WORKFLOW_REPO_NAME || "github_automation";
  const dispatchUrl = `https://api.github.com/repos/${owner}/${repoName}/dispatches`;

  try {
    const res = await fetch(dispatchUrl, {
      method: "POST",
      headers: {
        "Authorization": `token ${env.GITHUB_PAT}`,
        "Accept": "application/vnd.github.v3+json",
        "User-Agent": "Cloudflare-Worker-Telegram"
      },
      body: JSON.stringify({
        event_type: "ai_developer_task",
        client_payload: {
          target_repo: repo,
          user_prompt: prompt,
          telegram_chat_id: chatId
        }
      })
    });

    if (!res.ok) {
      console.error(`GitHub API dispatch failed (${res.status}): ${await res.text()}`);
    }
  } catch (err) {
    console.error("Error dispatching GitHub workflow from Telegram:", err);
  }
}

function escapeMarkdownV2(text) {
  return text.replace(/[_*[\]()~`>#+-=|{}.!]/g, "\\$&");
}

async function sendTelegramMessage(chatId, text, env) {
  const url = `https://api.telegram.org/bot${env.TELEGRAM_BOT_TOKEN}/sendMessage`;
  try {
    await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        chat_id: chatId,
        text: text,
        parse_mode: "MarkdownV2"
      })
    });
  } catch (e) {
    console.error("Failed to send Telegram message:", e);
  }
}
