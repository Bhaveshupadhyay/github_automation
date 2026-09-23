// Bounds the thread scan for a request header: 10 pages of 200 messages.
const MAX_THREAD_PAGES = 10;

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
      // The first Repo and Prompt markers in the thread. They can sit in different messages:
      // a request that named no repository gets its Repo marker when the reply supplies one.
      // A request made deep in a long thread has its header on a later page.
      let parentRepo = "";
      let parentPrompt = "";
      let cursor = "";
      for (let page = 0; page < MAX_THREAD_PAGES && !(parentRepo && parentPrompt); page++) {
        const queryParams = new URLSearchParams({ channel, ts: threadTs, limit: "200" });
        if (cursor) queryParams.set("cursor", cursor);

        const res = await fetch(
          `https://slack.com/api/conversations.replies?${queryParams.toString()}`,
          { headers: { "Authorization": `Bearer ${this.botToken}` } }
        );
        const data = await res.json();
        if (!data.ok || !Array.isArray(data.messages)) break;

        for (const msg of data.messages) {
          const text = msg.text || "";
          parentRepo ||= text.match(/Repo:\*\s*`([^`]+)`/)?.[1] || "";
          parentPrompt ||= text.match(/Prompt:\*\s*`([^`]+)`/)?.[1] || "";
        }

        cursor = data.response_metadata?.next_cursor || "";
        if (!cursor) break;
      }

      if (parentRepo || parentPrompt) {
        return { parentRepo, parentPrompt: parentPrompt || "Previous Coding Request" };
      }
    } catch (err) {
      console.error("[SlackService] Error fetching thread parent:", err);
    }

    return { parentRepo: "", parentPrompt: "" };
  }

  /**
   * Fetches a thread's messages, oldest first.
   * @param {string} channel
   * @param {string} threadTs
   * @returns {Promise<Array<{text?: string}>>}
   */
  async fetchThreadMessages(channel, threadTs) {
    if (!this.botToken) return [];

    try {
      const queryParams = new URLSearchParams({ channel, ts: threadTs, limit: "200" });
      const res = await fetch(
        `https://slack.com/api/conversations.replies?${queryParams.toString()}`,
        { headers: { "Authorization": `Bearer ${this.botToken}` } }
      );
      const data = await res.json();
      if (data.ok && Array.isArray(data.messages)) return data.messages;
      console.error("[SlackService] conversations.replies failed:", data.error);
    } catch (err) {
      console.error("[SlackService] Error fetching thread messages:", err);
    }
    return [];
  }
}
