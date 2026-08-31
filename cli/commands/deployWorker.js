import { spawnSync } from "node:child_process";
import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { c, logSuccess, logWarn, logError, logInfo, promptText, promptSecret } from "../ui.js";
import { parseRepoSlug } from "./check.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export function sanitizeWorkerName(name) {
  if (!name) return "slack-antigravity-worker";
  return name
    .toLowerCase()
    .replace(/[^a-z0-9-_]/g, "-")
    .replace(/-+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 63) || "slack-antigravity-worker";
}

export function setCloudflareSecret(key, val, wranglerTomlPath, workerDir) {
  if (!val) return false;
  try {
    const result = spawnSync("npx", ["wrangler", "secret", "put", key, "--config", wranglerTomlPath], {
      cwd: workerDir,
      input: val,
      encoding: "utf8",
      stdio: ["pipe", "ignore", "ignore"],
    });
    if (result.status === 0) {
      logSuccess(`Set Cloudflare secret: ${key}`);
      return true;
    }
    logWarn(`Could not automatically set Cloudflare secret ${key}`);
    return false;
  } catch (err) {
    logWarn(`Could not automatically set Cloudflare secret ${key}: ${err.message}`);
    return false;
  }
}

export async function deployCloudflareWorker(targetRepoSlug = null, credentials = {}) {
  console.log(`\n${c.bold("☁️  Cloudflare Worker Fast-Path Deployment")}\n`);

  const workerDir = path.resolve(__dirname, "../../cloudflare-worker");

  const parsed = parseRepoSlug(targetRepoSlug);
  let repoOwner = parsed.owner;
  let repoName = parsed.repo;

  if (repoOwner && repoName) {
    logInfo(`Target Workflow Repository: ${c.bold(c.brightGreen(`${repoOwner}/${repoName}`))}`);
  } else {
    repoOwner = await promptText("GitHub Workflow Repository Owner", repoOwner || "bhaveshupadhyay");
    repoName = await promptText("GitHub Workflow Repository Name", repoName || "github_automation");
  }

  const rawDefaultName = repoName ? `autopr-${repoName}` : "slack-antigravity-worker";
  const defaultWorkerName = sanitizeWorkerName(rawDefaultName);
  const inputWorkerName = await promptText("Cloudflare Worker name", defaultWorkerName);
  const workerName = sanitizeWorkerName(inputWorkerName);

  // Prompt for keys available before bot creation
  console.log(`\n${c.dim("Configure GitHub & Gemini Credentials (Press Enter to skip if already set):")}`);

  // Auto-detect PAT from env vars or active gh CLI session before prompting
  function resolveGithubPat() {
    const fromEnv = process.env.PAT_TOKEN || process.env.GITHUB_PAT || process.env.GH_TOKEN || process.env.GITHUB_TOKEN;
    if (fromEnv) return fromEnv;
    try {
      const token = execFileSync("gh", ["auth", "token"], { encoding: "utf8", stdio: ["ignore", "pipe", "ignore"] }).trim();
      if (token) return token;
    } catch (_) { /* not available */ }
    return null;
  }

  const detectedPat = credentials.patToken || resolveGithubPat();
  if (detectedPat) logInfo("GitHub token auto-detected — skipping PAT prompt.");
  const githubPat = detectedPat || await promptSecret("GitHub Personal Access Token (GITHUB_PAT / PAT_TOKEN)");
  const geminiApiKey = credentials.geminiApiKey || await promptSecret("Gemini API Key (GEMINI_API_KEY / AGY_API_KEY)");

  logInfo("Building and deploying Cloudflare Worker via Wrangler...");

  try {
    const wranglerTomlPath = path.join(workerDir, "wrangler.toml");
    const tomlContent = `name = "${workerName}"
main = "slack-worker.js"
compatibility_date = "2026-08-10"

[vars]
WORKFLOW_REPO_OWNER = "${repoOwner}"
WORKFLOW_REPO_NAME = "${repoName}"
`;
    await fs.writeFile(wranglerTomlPath, tomlContent, "utf8");

    // Execute wrangler deploy
    const deployResult = spawnSync("npx", ["wrangler", "deploy", "--config", wranglerTomlPath], {
      cwd: workerDir,
      encoding: "utf8",
      stdio: "pipe",
    });

    if (deployResult.status !== 0) {
      logError(`Wrangler deployment failed:\n${deployResult.stderr || deployResult.stdout}`);
      return { workerUrl: null, wranglerTomlPath, workerDir, credentials: { patToken: githubPat, geminiApiKey } };
    }

    const output = deployResult.stdout;
    const urlMatch = output.match(/https:\/\/[a-zA-Z0-9_-]+\.[a-zA-Z0-9_-]+\.workers\.dev/);
    const workerUrl = urlMatch ? urlMatch[0] : null;

    if (workerUrl) {
      logSuccess(`Worker successfully deployed to: ${c.bold(c.brightGreen(workerUrl))}`);
    } else {
      logSuccess("Worker deployed successfully!");
    }

    if (githubPat) setCloudflareSecret("GITHUB_PAT", githubPat, wranglerTomlPath, workerDir);
    if (geminiApiKey) setCloudflareSecret("GEMINI_API_KEY", geminiApiKey, wranglerTomlPath, workerDir);

    return {
      workerUrl,
      wranglerTomlPath,
      workerDir,
      credentials: {
        patToken: githubPat,
        geminiApiKey,
      },
    };
  } catch (err) {
    logError(`Deployment failed: ${err.message}`);
    return { workerUrl: null, credentials: { patToken: githubPat, geminiApiKey } };
  }
}
