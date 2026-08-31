import fs from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { c, logSuccess, logInfo, promptText } from "../ui.js";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

export async function generateSlackManifest(workerUrlInput = null, targetDir = process.cwd()) {
  console.log(`\n${c.bold("📱 Slack App Manifest Generation")}\n`);

  let workerUrl = workerUrlInput;
  if (!workerUrl) {
    workerUrl = await promptText(
      "Enter your Cloudflare Worker URL (e.g. https://slack-antigravity-worker.user.workers.dev)",
      "https://your-worker.workers.dev"
    );
  }

  const templatePath = path.join(__dirname, "../templates/slack-manifest.template.json");
  const templateRaw = await fs.readFile(templatePath, "utf8");
  const manifestContent = templateRaw.replaceAll("{{WORKER_URL}}", workerUrl);

  const outputPath = path.join(targetDir, "slack-app-manifest.json");
  await fs.writeFile(outputPath, manifestContent, "utf8");

  logSuccess(`Generated Slack Manifest: ${c.bold(c.brightGreen(outputPath))}`);
  
  console.log(`\n${c.bold("📋 How to use this Slack App Manifest:")}`);
  console.log(`  1. Go to ${c.cyan("https://api.slack.com/apps")} and click ${c.bold("'Create New App'")}.`);
  console.log(`  2. Select ${c.bold("'From an app manifest'")}.`);
  console.log(`  3. Choose your Slack workspace.`);
  console.log(`  4. Open and paste the content of:`);
     console.log(`     ${c.yellow(outputPath)}`);
  console.log(`  5. Click ${c.bold("'Create'")}, then click ${c.bold("'Install to Workspace'")}.`);
  console.log(`  6. Copy your ${c.bold("Bot User OAuth Token (xoxb-...)")} & ${c.bold("Signing Secret")}.\n`);

  return outputPath;
}
