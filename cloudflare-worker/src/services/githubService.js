/**
 * Service to handle GitHub Actions workflow dispatch triggers.
 */
export class GithubService {
  constructor(pat, owner = "bhaveshupadhyay", repoName = "github_automation") {
    this.pat = pat;
    this.owner = owner;
    this.repoName = repoName;
  }

  /**
   * Dispatches repository_dispatch API event to GitHub Actions runner.
   * @param {string} targetRepo 
   * @param {string} prompt 
   * @param {string} channelId 
   * @param {string|null} threadTs 
   * @returns {Promise<boolean>}
   */
  async dispatchWorkflow(targetRepo, prompt, channelId, threadTs = null) {
    if (!this.pat) {
      console.error("[GithubService] GITHUB_PAT token missing.");
      return false;
    }

    const dispatchUrl = `https://api.github.com/repos/${this.owner}/${this.repoName}/dispatches`;

    try {
      const res = await fetch(dispatchUrl, {
        method: "POST",
        headers: {
          "Authorization": `Bearer ${this.pat}`,
          "Accept": "application/vnd.github.v3+json",
          "User-Agent": "Cloudflare-Worker-Antigravity"
        },
        body: JSON.stringify({
          event_type: "ai_developer_task",
          client_payload: {
            target_repo: targetRepo,
            user_prompt: prompt,
            slack_channel: channelId,
            slack_thread_ts: threadTs
          }
        })
      });

      if (!res.ok) {
        const errText = await res.text();
        console.error(`[GithubService] Workflow dispatch failed (${res.status}): ${errText}`);
        return false;
      }

      console.log(`[GithubService] Successfully dispatched workflow for target repo: ${targetRepo}`);
      return true;
    } catch (err) {
      console.error("[GithubService] Dispatch error:", err);
      return false;
    }
  }
}
