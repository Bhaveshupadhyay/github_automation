/**
 * Cloudflare Worker: Multi-Repository Slack Webhook Bridge to GitHub Actions
 * Free serverless worker (100k free requests/day)
 * 
 * Syntax:
 * 1. Default Repo:   /code Add dark mode toggle
 * 2. Specific Repo:  /code owner/repo-name Add dark mode toggle
 * 3. Short Repo:     /code repo-name Add dark mode toggle (uses your default GitHub username)
 */

export default {
  async fetch(request, env) {
    if (request.method !== 'POST') {
      return new Response('Slack Multi-Repo Listener OK', { status: 200 });
    }

    try {
      const contentType = request.headers.get('content-type') || '';
      let text = '';
      let channelId = '';

      if (contentType.includes('application/x-www-form-urlencoded')) {
        const formData = await request.formData();
        text = (formData.get('text') || '').trim();
        channelId = formData.get('channel_id');
      } else if (contentType.includes('application/json')) {
        const body = await request.json();
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
          text: '👋 *Multi-Repo Usage:*\n• `/code <prompt>` (Default repo)\n• `/code <repo-name> <prompt>` (Target specific repo)\n• `/code <owner/repo> <prompt>`'
        }), { headers: { 'Content-Type': 'application/json' } });
      }

      // Parse repository name from text
      let targetRepo = env.DEFAULT_GITHUB_REPO; // e.g. "myusername/default-repo"
      let prompt = text;

      const words = text.split(' ');
      if (words.length > 1) {
        const firstWord = words[0];
        if (firstWord.includes('/')) {
          // Explicit owner/repo (e.g. myorg/backend-service)
          targetRepo = firstWord;
          prompt = words.slice(1).join(' ');
        } else if (env.GITHUB_OWNER && firstWord.endsWith('-app') || firstWord.endsWith('-service') || firstWord.endsWith('-repo')) {
          // Short name (e.g. frontend-app -> myusername/frontend-app)
          targetRepo = `${env.GITHUB_OWNER}/${firstWord}`;
          prompt = words.slice(1).join(' ');
        }
      }

      // Send immediate Slack acknowledgment
      const ackMessage = {
        response_type: 'in_channel',
        text: `⚡ *AI Developer Triggered!*\n> 📦 *Target Repo:* \`${targetRepo}\`\n> 📝 *Prompt:* \`${prompt}\`\n\n🔍 Dispatching task to GitHub Actions...`
      };

      // Trigger GitHub Repository Dispatch Event (either to target repo directly or central runner)
      const ghResponse = await fetch(`https://api.github.com/repos/${targetRepo}/dispatches`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${env.GITHUB_PAT}`,
          'Accept': 'application/vnd.github.v3+json',
          'User-Agent': 'Cloudflare-Slack-MultiRepo-Bot',
          'Content-Type': 'application/json'
        },
        body: JSON.stringify({
          event_type: 'slack_ai_request',
          client_payload: {
            prompt: prompt,
            target_repo: targetRepo,
            channel_id: channelId,
            platform: 'slack'
          }
        })
      });

      if (!ghResponse.ok) {
        const errorText = await ghResponse.text();
        return new Response(JSON.stringify({
          response_type: 'ephemeral',
          text: `❌ *GitHub Dispatch Failed for \`${targetRepo}\`*: \`${ghResponse.status} - ${errorText}\``
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
