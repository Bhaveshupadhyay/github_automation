/* ==========================================================================
   AutoPR Slack AI — Interactive Logic, Simulator & Analytics Tracking
   Google Analytics 4 Property: G-WRTRH44MBB
   ========================================================================== */

const GA_MEASUREMENT_ID = 'G-WRTRH44MBB';

/**
 * Dispatches a custom event to Google Analytics 4 via gtag.js
 * @param {string} eventName - Semantic name of the event
 * @param {Record<string, any>} eventParams - Contextual metadata properties
 */
function trackEvent(eventName, eventParams = {}) {
  try {
    if (typeof window.gtag === 'function') {
      window.gtag('event', eventName, {
        ...eventParams,
        send_to: GA_MEASUREMENT_ID,
      });
    }
  } catch (err) {
    console.warn(`[GA4 Error] Failed to track '${eventName}':`, err);
  }
}

/**
 * Categorize user Slack prompt for semantic analytics aggregation
 * @param {string} prompt 
 * @returns {string} category slug
 */
function categorizePrompt(prompt) {
  const text = (prompt || '').toLowerCase();
  if (text.includes('redis') || text.includes('cache')) return 'caching';
  if (text.includes('dark mode') || text.includes('theme') || text.includes('css')) return 'ui_styling';
  if (text.includes('test') || text.includes('pytest') || text.includes('unit')) return 'testing';
  if (text.includes('auth') || text.includes('race') || text.includes('token') || text.includes('lock')) return 'auth_security';
  if (text.includes('api') || text.includes('webhook') || text.includes('endpoint')) return 'api_development';
  return 'general_code_refactoring';
}

/**
 * Initializes global click event delegation to capture all user click interactions
 */
function initGlobalClickTracking() {
  document.addEventListener('click', (event) => {
    const clickable = event.target.closest(
      'a, button, [role="button"], input[type="button"], input[type="submit"], .chip, .tab-btn, .copy-btn'
    );
    if (!clickable) return;

    const tagName = clickable.tagName ? clickable.tagName.toLowerCase() : '';
    const elementId = clickable.id || '';
    const elementClasses = Array.from(clickable.classList || []).join(' ');

    const isInsideChat = Boolean(clickable.closest('#chatList'));
    const rawText = (
      clickable.innerText ||
      clickable.value ||
      clickable.getAttribute('aria-label') ||
      clickable.getAttribute('title') ||
      ''
    ).trim().slice(0, 80);

    // Omit arbitrary user-derived prompt text from chat elements to prevent PII leakage to GA4
    const elementText = isInsideChat ? '[Chat Link]' : rawText;

    const href = clickable.getAttribute('href') || '';
    const sectionContainer = clickable.closest('section, header, footer');
    const sectionName = sectionContainer ? (sectionContainer.id || sectionContainer.tagName.toLowerCase()) : 'page_body';
    const isOutbound = href.startsWith('http://') || href.startsWith('https://');

    // 1. Dispatch universal click interaction event
    trackEvent('ui_click', {
      element_tag: tagName,
      element_id: elementId || undefined,
      element_class: elementClasses || undefined,
      element_text: elementText || undefined,
      element_href: href || undefined,
      section_name: sectionName,
      is_outbound: isOutbound,
      event_category: 'User Interaction'
    });

    // 2. Track specific navigation categories
    if (isOutbound) {
      trackEvent('outbound_link_click', {
        link_url: href,
        link_text: elementText,
        section_name: sectionName,
        event_category: 'Navigation'
      });
    } else if (href.startsWith('#') && href.length > 1) {
      trackEvent('anchor_nav_click', {
        target_section: href.substring(1),
        link_text: elementText,
        section_name: sectionName,
        event_category: 'Navigation'
      });
    }

    // 3. Track PR links without user-derived PII payloads
    if (clickable.classList.contains('pr-link') || clickable.closest('.slack-attachment')) {
      trackEvent('pr_link_clicked', {
        section_name: sectionName,
        event_category: 'Simulator'
      });
    }
  });
}

// Lifecycle Initialization
document.addEventListener('DOMContentLoaded', () => {
  console.log('AutoPR Slack AI Portal loaded. Google Analytics Active:', GA_MEASUREMENT_ID);

  // Initialize global click tracking delegation
  initGlobalClickTracking();

  const input = document.getElementById('slackInput');
  if (input) {
    input.addEventListener('keydown', (e) => {
      if (e.key === 'Enter' && !e.shiftKey) {
        e.preventDefault();
        submitPrompt('keyboard_enter');
      }
    });
  }
});

// Interactive Slack Simulator Logic
function runPrompt(promptText) {
  trackEvent('prompt_chip_clicked', {
    prompt_category: categorizePrompt(promptText),
    event_category: 'Simulator'
  });

  const input = document.getElementById('slackInput');
  if (input) {
    input.value = promptText;
    submitPrompt('chip_click');
  }
}

function submitPrompt(source = 'button_click') {
  const input = document.getElementById('slackInput');
  const chatList = document.getElementById('chatList');
  if (!input || !chatList) return;

  const promptText = input.value.trim();
  if (!promptText) return;

  // Track command submission in GA4 using privacy-safe category & length (no raw text)
  trackEvent('simulator_command_submitted', {
    command_category: categorizePrompt(promptText),
    command_length: promptText.length,
    trigger_source: source,
    event_category: 'Simulator'
  });

  // Clear input box after reading
  input.value = '';

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

      // Track simulated PR creation success with privacy-safe properties
      trackEvent('simulator_pr_generated', {
        pr_number: prNumber,
        prompt_category: categorizePrompt(promptText),
        event_category: 'Simulator'
      });

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
                <strong>Branch:</strong> <code style="color: #c084fc;">${escapeHTML(branchName)}</code><br>
                <strong>PR #${prNumber}:</strong> <a href="#" class="pr-link" style="color: #38bdf8; text-decoration: none;">${escapeHTML(promptText.replace('/code', '').trim())}</a>
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
    return `<span class="diff-info">--- a/automation/main.py</span><br>
<span class="diff-info">+++ b/automation/main.py</span><br>
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

  const targetPane = document.getElementById(tabName);
  if (targetPane) {
    targetPane.classList.add('active');
  }

  const clickedBtn = (evt && evt.currentTarget) ? evt.currentTarget : null;
  if (clickedBtn) {
    clickedBtn.classList.add('active');
  }

  const tabTitle = clickedBtn ? clickedBtn.innerText.trim() : tabName;
  trackEvent('setup_tab_selected', {
    tab_id: tabName,
    tab_title: tabTitle,
    event_category: 'Documentation'
  });
}

// One-Click Code Copier
function copyCode(text, evt) {
  const btn = (evt && evt.currentTarget) ? evt.currentTarget : null;

  if (!navigator.clipboard) return;

  navigator.clipboard.writeText(text).then(() => {
    trackEvent('code_snippet_copied', {
      snippet_preview: (text || '').substring(0, 40),
      snippet_length: (text || '').length,
      event_category: 'Documentation'
    });

    if (btn) {
      const origText = btn.textContent;
      btn.textContent = 'Copied! ✓';
      btn.style.background = '#10b981';
      btn.style.borderColor = '#10b981';
      setTimeout(() => {
        btn.textContent = origText;
        btn.style.background = '';
        btn.style.borderColor = '';
      }, 2000);
    }
  }).catch(err => {
    console.error('Failed to copy to clipboard:', err);
  });
}

// Helper: Escape HTML
function escapeHTML(str) {
  return str.replace(/[&<>'"]/g, 
    tag => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' }[tag] || tag)
  );
}
