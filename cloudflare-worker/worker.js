/**
 * Cloudflare Worker: Telegram Webhook Bridge to GitHub Actions
 * Free serverless worker (100k free requests/day)
 * 
 * Env Variables Required in Cloudflare Worker Dashboard:
 * - GITHUB_PAT: Personal Access Token with repo scope
 * - GITHUB_REPO: "your-username/your-repo-name"
 * - TELEGRAM_BOT_TOKEN: Token from @BotFather
 * - ALLOWED_CHAT_ID: Your personal Telegram Chat ID (Security measure!)
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('Telegram Webhook Listener OK', { status: 200 });
    }

    try {
      const update = await request.json();
      const message = update.message;

      if (!message || !message.text) {
        return new Response('OK', { status: 200 });
      }

      const chatId = message.chat.id;
      const text = message.text.trim();

      // Security check: Only process messages from your Telegram user/chat ID
      if (env.ALLOWED_CHAT_ID && chatId.toString() !== env.ALLOWED_CHAT_ID.toString()) {
        await sendTelegramReply(env.TELEGRAM_BOT_TOKEN, chatId, '⛔ Unauthorized user.');
        return new Response('Forbidden', { status: 403 });
      }

      // Check if command starts with /code or message text
      let prompt = text;
      if (text.startsWith('/code')) {
        prompt = text.replace('/code', '').trim();
      }

      if (!prompt || prompt === '/start') {
        await sendTelegramReply(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          '👋 *Welcome to Autonomous AI Code Bot!*\n\nUsage: Send `/code <your modification prompt>` or any text request.\nExample: `/code Add a dark mode toggle button`'
        );
        return new Response('OK', { status: 200 });
      }

      // Send initial acknowledgement to Telegram
      await sendTelegramReply(
        env.TELEGRAM_BOT_TOKEN,
        chatId,
        `⏳ *Request Received!*\nDispatching task to GitHub Actions...\n\n*Prompt:* \`${prompt}\``
      );

      // Trigger GitHub Repository Dispatch Event
      const ghResponse = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Cloudflare-Telegram-Bot',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          event_type: 'telegram_ai_request',
          client_payload: {
            prompt: prompt,
            chat_id: chatId.toString()
          }
        })
      });

      if (!ghResponse.ok) {
        const errorText = await ghResponse.text();
        await sendTelegramReply(
          env.TELEGRAM_BOT_TOKEN,
          chatId,
          `❌ *Failed to trigger GitHub Action*: \`${ghResponse.status} - ${errorText}\``
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
    body: JSON.stringify({
      chat_id: chatId,
      text: text,
      parse_mode: 'Markdown'
    })
  });
}
