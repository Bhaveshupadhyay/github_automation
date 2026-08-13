/* ==========================================================================
   AutoPR Slack AI — Interactive Logic & Simulator
   ========================================================================== */

document.addEventListener('DOMContentLoaded', () => {
  console.log('AutoPR Slack AI Portal loaded.');
});

// Interactive Slack Simulator Logic
function runPrompt(promptText) {
  const input = document.getElementById('slackInput');
  if (input) {
    input.value = promptText;
    submitPrompt();
  }
}

function submitPrompt() {
  const input = document.getElementById('slackInput');
  const chatList = document.getElementById('chatList');
  if (!input || !chatList) return;

  const promptText = input.value.trim();
  if (!promptText) return;

  const nowTime = new Date().toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });

  // 1. Append User Command Message
  const userMsgHTML = `
    <div class="message-item">
      <div class="avatar avatar-user">B</div>
      <div class="msg-content">
        <div class="msg-header">
          <span class="sender-name">Bhavesh</span>
          <span class="msg-time">Today at ${nowTime}</span>
        </div>
        <div class="msg-text">
          <span class="slack-cmd">${escapeHTML(promptText)}</span>
        </div>
      </div>
    </div>
  `;
  chatList.insertAdjacentHTML('beforeend', userMsgHTML);

  // 2. Append Typing / Loading Indicator Bot Message
  const loadingId = 'loading-' + Date.now();
  const loadingMsgHTML = `
    <div class="message-item" id="${loadingId}">
      <div class="avatar avatar-bot">⚡</div>
      <div class="msg-content">
        <div class="msg-header">
          <span class="sender-name">AutoPR AI Bot</span>
          <span class="bot-tag">APP</span>
          <span class="msg-time">Today at ${nowTime}</span>
        </div>
        <div class="msg-text" style="color: #9ca3af; display: flex; align-items: center; gap: 0.5rem;">
          <span class="indicator active" style="width: 8px; height: 8px; border-radius: 50%; background: #6366f1; display: inline-block;"></span>
          Receiving webhook on Cloudflare Edge... Spawning Antigravity Engine (\`agy\`) on GitHub Actions VM...
        </div>
      </div>
    </div>
  `;
  chatList.insertAdjacentHTML('beforeend', loadingMsgHTML);

  // Scroll to bottom
  chatList.scrollTop = chatList.scrollHeight;

  // 3. Simulate AI Reasoning & PR Creation Response after 1.2s delay
  setTimeout(() => {
    const loadingElem = document.getElementById(loadingId);
    if (loadingElem) {
      const branchName = generateBranchName(promptText);
      const prNumber = Math.floor(Math.random() * 80) + 120;
      const diffCode = generateDiff(promptText);

      loadingElem.outerHTML = `
        <div class="message-item">
          <div class="avatar avatar-bot">⚡</div>
          <div class="msg-content">
            <div class="msg-header">
              <span class="sender-name">AutoPR AI Bot</span>
              <span class="bot-tag">APP</span>
              <span class="msg-time">Today at ${nowTime}</span>
            </div>
            <div class="msg-text">
              🤖 Executed multi-agent reasoning with <strong>Google Antigravity Engine (\`agy\`)</strong>. Pull request generated!
            </div>

            <div class="slack-attachment">
              <div class="attachment-title">
                <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
                  <path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"></path>
                  <polyline points="22 4 12 14.01 9 11.01"></polyline>
                </svg>
                GitHub Pull Request #${prNumber} Created
              </div>
              <div style="font-size: 0.9rem; color: var(--text-muted);">
                <strong>Branch:</strong> <code style="color: #c084fc;">${branchName}</code><br>
                <strong>PR #${prNumber}:</strong> <a href="#" style="color: #38bdf8; text-decoration: none;">${escapeHTML(promptText.replace('/code', '').trim())}</a>
              </div>
              <div class="diff-preview">
                ${diffCode}
              </div>
            </div>
          </div>
        </div>
      `;
      chatList.scrollTop = chatList.scrollHeight;
    }
  }, 1200);
}

// Generate Branch Name from Prompt
function generateBranchName(prompt) {
  const clean = prompt.replace('/code', '').trim().toLowerCase().replace(/[^a-z0-9 ]/g, '').replace(/\s+/g, '-');
  return `feature/${clean.substring(0, 30) || 'ai-feature-update'}`;
}

// Generate Contextual Diff Preview
function generateDiff(prompt) {
  const text = prompt.toLowerCase();
  if (text.includes('redis') || text.includes('cache')) {
    return `<span class="diff-info">--- a/src/api.py</span><br>
<span class="diff-info">+++ b/src/api.py</span><br>
<span class="diff-del">- return db.get_user(user_id)</span><br>
<span class="diff-add">+ cached = await redis.get(f"user:{user_id}")</span><br>
<span class="diff-add">+ if cached: return json.loads(cached)</span><br>
<span class="diff-add">+ user = db.get_user(user_id)</span><br>
<span class="diff-add">+ await redis.setex(f"user:{user_id}", 3600, json.dumps(user))</span><br>
<span class="diff-add">+ return user</span>`;
  } else if (text.includes('dark mode')) {
    return `<span class="diff-info">--- a/src/style.css</span><br>
<span class="diff-info">+++ b/src/style.css</span><br>
<span class="diff-add">+ body.dark-mode {</span><br>
<span class="diff-add">+   background-color: #090d16;</span><br>
<span class="diff-add">+   color: #f8fafc;</span><br>
<span class="diff-add">+ }</span>`;
  } else if (text.includes('test')) {
    return `<span class="diff-info">--- a/tests/test_webhook.py</span><br>
<span class="diff-info">+++ b/tests/test_webhook.py</span><br>
<span class="diff-add">+ def test_webhook_dispatch():</span><br>
<span class="diff-add">+     response = client.post("/webhook", json={"command": "/code add feature"})</span><br>
<span class="diff-add">+     assert response.status_code == 200</span><br>
<span class="diff-add">+     assert "repository_dispatch" in response.json()</span>`;
  } else {
    return `<span class="diff-info">--- a/src/runner.py</span><br>
<span class="diff-info">+++ b/src/runner.py</span><br>
<span class="diff-del">- # Pending implementation</span><br>
<span class="diff-add">+ # Applied AST precision diff via Google Antigravity Engine</span><br>
<span class="diff-add">+ result = agy.execute_prompt("${escapeHTML(prompt.replace('/code', '').trim())}")</span>`;
  }
}

// Tabbed Setup Guide Controller
function openTab(evt, tabName) {
  const tabPanes = document.getElementsByClassName('tab-pane');
  for (let pane of tabPanes) {
    pane.classList.remove('active');
  }

  const tabBtns = document.getElementsByClassName('tab-btn');
  for (let btn of tabBtns) {
    btn.classList.remove('active');
  }

  document.getElementById(tabName).classList.add('active');
  evt.currentTarget.classList.add('active');
}

// One-Click Code Copier
function copyCode(text) {
  navigator.clipboard.writeText(text).then(() => {
    const btn = event.target;
    const origText = btn.textContent;
    btn.textContent = 'Copied! ✓';
    btn.style.background = '#10b981';
    btn.style.borderColor = '#10b981';
    setTimeout(() => {
      btn.textContent = origText;
      btn.style.background = '';
      btn.style.borderColor = '';
    }, 2000);
  });
}

// Helper: Escape HTML
function escapeHTML(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}
