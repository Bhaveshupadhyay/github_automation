/**
 * Cloudflare Worker: Multi-Repository Telegram Webhook Bridge to GitHub Actions
 * Free serverless worker (100k free requests/day)
 * 
 * Syntax:
 * 1. Default Repo:   /code Add dark mode toggle
 * 2. Specific Repo:  /code owner/repo-name Add dark mode toggle
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('Telegram Multi-Repo Listener OK', { status: 200 });
    }

    try {
      const update = await request.json();
      const message = update.message;

      if (!message || !message.text) {
        return new Response('OK', { status: 200 });
      }

      const chatId = message.chat.id;
      const text = message.text.trim();

      if (env.ALLOWED_CHAT_ID && chatId.toString() !== env.ALLOWED_CHAT_ID.toString()) {
        await sendTelegramReply(env.TELEGRAM_BOT_TOKEN, chatId, '⛔ Unauthorized user.');
        return new Response('Forbidden', { status: 403 });
      }

      let rawText = text.startsWith('/code') ? text.replace('/code', '').trim() : text;

      if (!rawText || rawText === '/start') {
        await sendTelegramReply(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          '👋 *Welcome to Autonomous Multi-Repo AI Developer!*\n\n*Usage:*\n• `/code <prompt>` (Default repo)\n• `/code <owner/repo> <prompt>` (Target specific repo)'
        );
        return new Response('OK', { status: 200 });
      }

      let targetRepo = env.DEFAULT_GITHUB_REPO;
      let prompt = rawText;

      const words = rawText.split(' ');
      if (words.length > 1 && words[0].includes('/')) {
        targetRepo = words[0];
        prompt = words.slice(1).join(' ');
      }

      await sendTelegramReply(
        env.TELEGRAM_BOT_TOKEN,
        chatId,
        `⚡ *AI Developer Triggered!*\n> 📦 *Target Repo:* \`${targetRepo}\`\n> 📝 *Prompt:* \`${prompt}\`\n\n🔍 Dispatching to GitHub Actions...`
      );

      const ghResponse = await fetch(`https://api.github.com/repos/${targetRepo}/dispatches`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Cloudflare-Telegram-MultiRepo-Bot',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          event_type: 'telegram_ai_request',
          client_payload: {
            prompt: prompt,
            target_repo: targetRepo,
            chat_id: chatId.toString()
          }
        })
      });

      if (!ghResponse.ok) {
        const errorText = await ghResponse.text();
        await sendTelegramReply(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          `❌ *GitHub Dispatch Failed for \`${targetRepo}\`*: \`${ghResponse.status} - ${errorText}\``
        );
      }

      return new Response('OK', { status: 200 });
    } catch (err) {
      return new Response(`Error: ${err.message}`, { status: 500 });
    }
  }
};

async function sendTelegramReply(botToken, chatId, text) {
  await fetch(`https://api.telegram.org/bot${botToken}/sendMessage`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ chat_id: chatId, text: text, parse_mode: 'Markdown' })
  });
}
