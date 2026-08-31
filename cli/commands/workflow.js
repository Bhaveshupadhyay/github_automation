import fs from "node:fs/promises";
import path from "node:path";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";
import { c, logSuccess, logWarn, logInfo, promptSelect, promptConfirm } from "../ui.js";
import { checkCommandAvailable, getGhAuthStatus, parseRepoSlug } from "./check.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const VALID_REPO_REGEX = /^[A-Za-z0-9_.-]+\/[A-Za-z0-9_.-]+$/;

export async function pushWorkflowToRemoteGithub(targetRepo, remoteFilePath, content) {
  if (!targetRepo || !VALID_REPO_REGEX.test(targetRepo)) {
    logWarn(`Invalid repository slug format: ${targetRepo}. Skipping remote push.`);
    return false;
  }

  const contentBase64 = Buffer.from(content).toString("base64");
  const cleanPath = remoteFilePath.replace(/^\.?\/?/, "");

  let sha = null;
  try {
    const existingJson = execFileSync(
      "gh",
      ["api", `/repos/${targetRepo}/contents/${cleanPath}`],
      { encoding: "utf8", stdio: ["pipe", "pipe", "ignore"] }
    );
    const parsed = JSON.parse(existingJson);
    sha = parsed.sha;
  } catch {
    // File does not exist yet
  }

  const payload = {
    message: "ci: add AutoPR AI Autonomous Developer workflow",
    content: contentBase64,
    ...(sha ? { sha } : {}),
  };

  try {
    execFileSync(
      "gh",
      ["api", "--method", "PUT", `/repos/${targetRepo}/contents/${cleanPath}`, "--input", "-"],
      {
        input: JSON.stringify(payload),
        encoding: "utf8",
        stdio: ["pipe", "pipe", "pipe"],
      }
    );
    logSuccess(`Pushed workflow file directly to GitHub: ${c.bold(c.brightGreen(`https://github.com/${targetRepo}/blob/main/${cleanPath}`))}`);
    return true;
  } catch (err) {
    logWarn(`Could not automatically push to GitHub API: ${err.message}`);
    return false;
  }
}

export async function installWorkflow(targetDir = process.cwd(), targetRepoSlug = null, forcedMode = null) {
  const workflowsDir = path.join(targetDir, ".github", "workflows");
  await fs.mkdir(workflowsDir, { recursive: true });

  let mode = forcedMode;
  if (!mode) {
    mode = await promptSelect("Which workflow type would you like to install?", [
      {
        title: "PyPI uvx Workflow (Recommended)",
        description: "Zero maintenance; pulls latest github-automation-ai on-the-fly from PyPI",
        value: "uvx",
      },
      {
        title: "Reusable Caller Workflow",
        description: "Delegates execution to central AutoPR engine via workflow_call",
        value: "reusable",
      },
      {
        title: "Standalone Full Workflow",
        description: "Copies complete multi-step actions workflow into your repository",
        value: "standalone",
      },
    ]);
  }

  let templateFile;
  if (mode === "uvx") {
    templateFile = path.join(__dirname, "../templates/workflow-uvx.yml");
  } else if (mode === "reusable") {
    templateFile = path.join(__dirname, "../templates/workflow-reusable.yml");
  } else {
    templateFile = path.join(__dirname, "../../.github/workflows/ai-autonomous-developer.yml");
  }

  const workflowFileName = mode === "standalone" ? "ai-autonomous-developer.yml" : "autopr.yml";
  const destinationFile = path.join(workflowsDir, workflowFileName);

  const content = await fs.readFile(templateFile, "utf8");
  await fs.writeFile(destinationFile, content, "utf8");

  logSuccess(`Created local workflow file: ${c.bold(c.brightGreen(path.relative(targetDir, destinationFile)))}`);

  // If a remote target repo is provided and gh is available, offer to push directly to GitHub
  const parsedRepo = parseRepoSlug(targetRepoSlug);
  const repoSlug = parsedRepo.slug;

  if (repoSlug && VALID_REPO_REGEX.test(repoSlug) && checkCommandAvailable("gh") && getGhAuthStatus().ok) {
    const shouldPushRemote = await promptConfirm(
      `Push workflow file directly to remote GitHub repository (${c.brightGreen(repoSlug)})?`,
      true
    );
    if (shouldPushRemote) {
      await pushWorkflowToRemoteGithub(repoSlug, `.github/workflows/${workflowFileName}`, content);
    }
  }

  return destinationFile;
}
