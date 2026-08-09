/**
 * Cloudflare Worker: Slack Webhook Bridge to GitHub Actions
 * Free serverless worker (100k free requests/day)
 * 
 * Env Variables Required in Cloudflare Worker Dashboard:
 * - GITHUB_PAT: Personal Access Token with repo scope
 * - GITHUB_REPO: "your-username/your-repo-name"
 * - SLACK_BOT_TOKEN: Bot User OAuth Token from api.slack.com (xoxb-...)
 * - SLACK_SIGNING_SECRET: (Optional) Signing secret for verification
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('Slack Webhook Listener OK', { status: 200 });
    }

    try {
      const contentType = request.headers.get('content-type') || '';
      let text = '';
      let channelId = '';
      let responseUrl = '';

      if (contentType.includes('application/x-www-form-urlencoded')) {
        // Form payload from Slack Slash Command (e.g. /code prompt)
        const formData = await request.formData();
        text = (formData.get('text') || '').trim();
        channelId = formData.get('channel_id');
        responseUrl = formData.get('response_url');
      } else if (contentType.includes('application/json')) {
        // JSON payload from Slack Event Subscription (@bot mention)
        const body = await request.json();
        
        // Handle Slack URL verification challenge during setup
        if (body.type === 'url_verification') {
          return new Response(JSON.stringify({ challenge: body.challenge }), {
            headers: { 'Content-Type': 'application/json' }
          });
        }

        if (body.event && body.event.type === 'app_mention') {
          text = body.event.text.replace(/<@[A-Z0-9]+>/g, '').trim();
          channelId = body.event.channel;
        }
      }

      if (!text) {
        return new Response(JSON.stringify({
          response_type: 'ephemeral',
          text: '👋 *Usage:* `/code <your requested prompt>`'
        }), { headers: { 'Content-Type': 'application/json' } });
      }

      // Immediately acknowledge Slack user
      const ackMessage = {
        response_type: 'in_channel',
        text: `⚡ *AI Developer Triggered!*\n> *Prompt:* \`${text}\`\n\n🔍 Dispatching task to GitHub Actions...`
      };

      // Trigger GitHub Repository Dispatch Event
      const ghResponse = await fetch(`https://api.github.com/repos/${env.GITHUB_REPO}/dispatches`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Cloudflare-Slack-Bot',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          event_type: 'telegram_ai_request', // reused event type or slack_ai_request
          client_payload: {
            prompt: text,
            channel_id: channelId,
            platform: 'slack'
          }
        })
      });

      if (!ghResponse.ok) {
        const errorText = await ghResponse.text();
        return new Response(JSON.stringify({
          response_type: 'ephemeral',
          text: `❌ *GitHub Dispatch Failed:* \`${ghResponse.status} - ${errorText}\``
        }), { headers: { 'Content-Type': 'application/json' } });
      }

      return new Response(JSON.stringify(ackMessage), {
        headers: { 'Content-Type': 'application/json' }
      });

    } catch (err) {
      return new Response(`Error: ${err.message}`, { status: 500 });
    }
  }
};
