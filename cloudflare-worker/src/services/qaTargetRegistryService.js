/**
 * Reads the QA target registry (contracts/qa-targets.json) from github_automation, so
 * the repositories served are configured in one place, beside the pipeline itself.
 */

const CACHE_TTL_MS = 60_000;

export class QaTargetRegistryService {
  constructor(pat, owner = "bhaveshupadhyay", repoName = "github_automation", path = "contracts/qa-targets.json", ref = "main") {
    this.pat = pat;
    this.url = `https://api.github.com/repos/${owner}/${repoName}/contents/${path}?ref=${encodeURIComponent(ref)}`;
    this.cached = null;
    this.cachedAt = 0;
  }

  /**
   * Returns the registry, cached briefly so a burst of webhooks makes one API call.
   * @returns {Promise<{targets: Object<string, Object>}>}
   */
  async getRegistry() {
    if (this.cached && Date.now() - this.cachedAt < CACHE_TTL_MS) {
      return this.cached;
    }

    const headers = {
      "Accept": "application/vnd.github.raw+json",
      "User-Agent": "Cloudflare-Worker-Antigravity"
    };
    if (this.pat) headers["Authorization"] = `Bearer ${this.pat}`;

    const res = await fetch(this.url, { headers });
    if (!res.ok) {
      throw new Error(`Could not read the QA target registry (${res.status}): ${await res.text()}`);
    }
    this.cached = await res.json();
    this.cachedAt = Date.now();
    return this.cached;
  }
}
