import { execSync } from "node:child_process";
import fs from "node:fs";
import path from "node:path";
import os from "node:os";
import { c, logSuccess, logWarn, logError, logInfo, promptSecret, promptConfirm } from "../ui.js";
import { checkCommandAvailable, getGhAuthStatus, getCurrentGitRepo, parseRepoSlug } from "./check.js";
import { setCloudflareSecret } from "./deployWorker.js";

export async function configureSecrets(repoSlug = null, credentials = {}, workerConfig = null) {
  const parsed = parseRepoSlug(repoSlug);
  const targetRepo = parsed.slug || repoSlug || getCurrentGitRepo();

  if (!checkCommandAvailable("gh")) {
    logWarn("GitHub CLI (gh) not detected. Please manually set repository secrets.");
    return false;
  }

  const auth = getGhAuthStatus();
  if (!auth.ok) {
    logWarn("GitHub CLI is not logged in. Run 'gh auth login' to enable automated secrets provisioning.");
    return false;
  }

  console.log(`\n${c.bold("🔐 Secrets Provisioning (GitHub Actions & Cloudflare Worker)")}`);
  if (targetRepo) {
    console.log(`Target GitHub Repository: ${c.brightGreen(targetRepo)}\n`);
  }

  const repoFlag = targetRepo ? `-R "${targetRepo}"` : "";

  // 1. PAT_TOKEN
  const patToken = credentials.patToken || await promptSecret("Enter GitHub Personal Access Token (PAT_TOKEN / GITHUB_PAT)");
  if (patToken) {
    try {
      execSync(`gh secret set PAT_TOKEN ${repoFlag}`, {
        input: patToken,
        encoding: "utf8",
        stdio: ["pipe", "ignore", "ignore"],
      });
      logSuccess("Configured GitHub secret: PAT_TOKEN");
    } catch (e) {
      logError(`Failed to set PAT_TOKEN on GitHub: ${e.message}`);
    }
  }

  // 2. SLACK_BOT_TOKEN (Now available after user creates App from Manifest)
  const slackToken = credentials.slackBotToken || await promptSecret("Enter Slack Bot User OAuth Token (SLACK_BOT_TOKEN - xoxb-...)");
  if (slackToken) {
    try {
      execSync(`gh secret set SLACK_BOT_TOKEN ${repoFlag}`, {
        input: slackToken,
        encoding: "utf8",
        stdio: ["pipe", "ignore", "ignore"],
      });
      logSuccess("Configured GitHub secret: SLACK_BOT_TOKEN");
    } catch (e) {
      logError(`Failed to set SLACK_BOT_TOKEN on GitHub: ${e.message}`);
    }

    if (workerConfig?.wranglerTomlPath && workerConfig?.workerDir) {
      setCloudflareSecret("SLACK_BOT_TOKEN", slackToken, workerConfig.wranglerTomlPath, workerConfig.workerDir);
    }
  }

  // 3. SLACK_SIGNING_SECRET
  const slackSigningSecret = credentials.slackSigningSecret || await promptSecret("Enter Slack Signing Secret (SLACK_SIGNING_SECRET)");
  if (slackSigningSecret && workerConfig?.wranglerTomlPath && workerConfig?.workerDir) {
    setCloudflareSecret("SLACK_SIGNING_SECRET", slackSigningSecret, workerConfig.wranglerTomlPath, workerConfig.workerDir);
  }

  // 4. AGY_API_KEY / GEMINI_API_KEY
  const geminiKey = credentials.geminiApiKey || await promptSecret("Enter Gemini / Antigravity API Key (AGY_API_KEY / GEMINI_API_KEY)");
  if (geminiKey) {
    try {
      execSync(`gh secret set AGY_API_KEY ${repoFlag}`, {
        input: geminiKey,
        encoding: "utf8",
        stdio: ["pipe", "ignore", "ignore"],
      });
      logSuccess("Configured GitHub secret: AGY_API_KEY");
    } catch (e) {
      logError(`Failed to set AGY_API_KEY on GitHub: ${e.message}`);
    }
  }

  // 5. AGY_AUTH_CONFIG (Auto-detect from ~/.gemini if exists)
  const homeDir = os.homedir();
  const oauthCredsPath = path.join(homeDir, ".gemini", "oauth_creds.json");
  const agyTokenPath = path.join(homeDir, ".gemini", "antigravity-cli", "antigravity-oauth-token");

  if (fs.existsSync(oauthCredsPath)) {
    const shouldAutoUpload = await promptConfirm("Detected local ~/.gemini/oauth_creds.json. Upload as AGY_AUTH_CONFIG?");
    if (shouldAutoUpload) {
      try {
        const fileData = fs.readFileSync(oauthCredsPath);
        const b64 = fileData.toString("base64");
        execSync(`gh secret set AGY_AUTH_CONFIG ${repoFlag}`, {
          input: b64,
          encoding: "utf8",
          stdio: ["pipe", "ignore", "ignore"],
        });
        logSuccess("Configured GitHub secret: AGY_AUTH_CONFIG (auto-encoded base64)");
      } catch (e) {
        logError(`Failed to set AGY_AUTH_CONFIG: ${e.message}`);
      }
    }
  }

  if (fs.existsSync(agyTokenPath)) {
    const shouldAutoUploadToken = await promptConfirm("Detected local Antigravity OAuth token. Upload as AGY_SESSION_DATA?");
    if (shouldAutoUploadToken) {
      try {
        const fileData = fs.readFileSync(agyTokenPath);
        const b64 = fileData.toString("base64");
        execSync(`gh secret set AGY_SESSION_DATA ${repoFlag}`, {
          input: b64,
          encoding: "utf8",
          stdio: ["pipe", "ignore", "ignore"],
        });
        logSuccess("Configured GitHub secret: AGY_SESSION_DATA (auto-encoded base64)");
      } catch (e) {
        logError(`Failed to set AGY_SESSION_DATA: ${e.message}`);
      }
    }
  }

  return true;
}
