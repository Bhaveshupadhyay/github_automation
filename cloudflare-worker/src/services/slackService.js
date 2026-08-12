/**
 * Service to handle Slack messaging and thread replies context retrieval.
 */
export class SlackService {
  constructor(botToken) {
    this.botToken = botToken;
  }

  /**
   * Posts a message to a Slack channel or thread.
   * @param {string} channel 
   * @param {string} text 
   * @param {string|null} threadTs 
   * @returns {Promise<string|null>} Returns message timestamp (ts) if successful.
   */
  async postMessage(channel, text, threadTs = null) {
    if (!this.botToken) {
      console.warn("[SlackService] Bot token missing. Skipping Slack postMessage.");
      return null;
    }

    try {
      const payload = { channel, text };
      if (threadTs) {
        payload.thread_ts = threadTs;
      }

      const res = await fetch("https://slack.com/api/chat.postMessage", {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${this.botToken}`,
          "Content-Type": "application/json; charset=utf-8"
        },
        body: JSON.stringify(payload)
      });

      const data = await res.json();
      if (data.ok) {
        return data.ts;
      } else {
        console.error("[SlackService] postMessage failed:", data.error);
      }
    } catch (err) {
      console.error("[SlackService] Error posting message:", err);
    }
    return null;
  }

  /**
   * Fetches parent thread message to reconstruct target repo and original prompt.
   * @param {string} channel 
   * @param {string} threadTs 
   * @returns {Promise<{ parentRepo: string, parentPrompt: string }>}
   */
  async fetchThreadParent(channel, threadTs) {
    if (!this.botToken) {
      return { parentRepo: "", parentPrompt: "" };
    }

    try {
      const queryParams = new URLSearchParams({
        channel: channel,
        ts: threadTs,
        limit: "10"
      });

      const res = await fetch(
        `https://slack.com/api/conversations.replies?${queryParams.toString()}`,
        { headers: { "Authorization": `Bearer ${this.botToken}` } }
      );

      const data = await res.json();
      if (data.ok && Array.isArray(data.messages)) {
        // Search through messages in the thread to find the context marker
        for (const msg of data.messages) {
          const text = msg.text || "";
          const repoMatch = text.match(/Repo:\*\s*`([^`]+)`/);
          const promptMatch = text.match(/Prompt:\*\s*`([^`]+)`/);

          if (repoMatch || promptMatch) {
            return {
              parentRepo: repoMatch ? repoMatch[1] : "",
              parentPrompt: promptMatch ? promptMatch[1] : "Previous Coding Request"
            };
          }
        }
      }
    } catch (err) {
      console.error("[SlackService] Error fetching thread parent:", err);
    }

    return { parentRepo: "", parentPrompt: "" };
  }
}
