import { execSync } from "node:child_process";
import { c, logSuccess, logWarn, logError, logInfo } from "../ui.js";

export function checkCommandAvailable(cmd) {
  try {
    execSync(`which ${cmd}`, { stdio: "ignore" });
    return true;
  } catch {
    return false;
  }
}

export function getGhAuthStatus() {
  try {
    const out = execSync("gh auth status", { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] });
    return { ok: true, output: out };
  } catch (err) {
    return { ok: false, output: err.message };
  }
}

export function parseRepoSlug(input) {
  if (!input) return { owner: "", repo: "", slug: "" };
  let str = input.trim();
  // Strip URL prefixes
  str = str.replace(/^(https?:\/\/github\.com\/|git@github\.com:)/i, "");
  // Strip .git suffix and trailing slashes
  str = str.replace(/\.git\/?$/i, "").replace(/\/+$/, "");
  const parts = str.split("/").filter(Boolean);
  if (parts.length >= 2) {
    const owner = parts[parts.length - 2].trim();
    const repo = parts[parts.length - 1].trim();
    return { owner, repo, slug: `${owner}/${repo}` };
  }
  return { owner: "", repo: str, slug: str };
}

export function getCurrentGitRepo() {
  try {
    const origin = execSync("git config --get remote.origin.url", { encoding: "utf8", stdio: ["ignore", "pipe", "pipe"] }).trim();
    const parsed = parseRepoSlug(origin);
    if (parsed.owner && parsed.repo) {
      return parsed.slug;
    }
  } catch {
    // Not a git repo
  }
  return null;
}

export async function runHealthCheck() {
  console.log(`\n${c.bold("🔍 Running System & Environment Diagnostics...")}\n`);

  let allPassed = true;

  // 1. Node.js
  const nodeVersion = process.version;
  logSuccess(`Node.js Runtime: ${c.cyan(nodeVersion)}`);

  // 2. Git
  if (checkCommandAvailable("git")) {
    logSuccess("Git CLI installed");
    const repo = getCurrentGitRepo();
    if (repo) {
      logSuccess(`Current Git Repository: ${c.bold(c.brightGreen(repo))}`);
    } else {
      logInfo("Current directory is not a recognized GitHub git repository");
    }
  } else {
    logError("Git CLI not found in PATH");
    allPassed = false;
  }

  // 3. GitHub CLI (gh)
  if (checkCommandAvailable("gh")) {
    logSuccess("GitHub CLI (gh) installed");
    const auth = getGhAuthStatus();
    if (auth.ok) {
      logSuccess("GitHub CLI is authenticated");
    } else {
      logWarn("GitHub CLI is not logged in. Run 'gh auth login' to enable automated secrets provisioning.");
    }
  } else {
    logWarn("GitHub CLI (gh) not found. Manual secret configuration will be required.");
  }

  // 4. Wrangler CLI
  if (checkCommandAvailable("wrangler") || checkCommandAvailable("npx")) {
    logSuccess("Wrangler CLI / npx is available for Cloudflare Worker deployment");
  } else {
    logWarn("Neither wrangler nor npx found for Cloudflare Worker deployment");
  }

  console.log();
  return allPassed;
}
