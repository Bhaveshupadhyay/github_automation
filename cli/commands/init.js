import { c, renderBanner, logSuccess, logInfo, logStep, promptText, promptConfirm } from "../ui.js";
import { runHealthCheck, getCurrentGitRepo, parseRepoSlug } from "./check.js";
import { installWorkflow } from "./workflow.js";
import { configureSecrets } from "./secrets.js";
import { deployCloudflareWorker } from "./deployWorker.js";
import { generateSlackManifest } from "./manifest.js";

export async function runInitWizard() {
  renderBanner();

  console.log(`Welcome! This wizard will configure ${c.bold("AutoPR Slack AI")} for your repository.`);
  console.log(`No manual cloning or complex environment setup required.\n`);

  // Step 1: Healthcheck & Git repo detection
  logStep(1, 5, "Diagnostics & Target Repository Resolution");
  await runHealthCheck();

  const detectedRepo = getCurrentGitRepo();
  const rawInput = await promptText(
    "Target GitHub Repository (owner/repo or URL)",
    detectedRepo || "bhaveshupadhyay/github_automation"
  );
  const parsedRepo = parseRepoSlug(rawInput);
  const targetRepo = parsedRepo.slug || rawInput;

  logInfo(`Configured Target Repository: ${c.bold(c.brightGreen(targetRepo))}`);

  // Step 2: Workflow setup
  logStep(2, 5, "GitHub Actions Workflow Setup");
  const shouldInstallWorkflow = await promptConfirm("Install AutoPR GitHub Actions workflow in this repository?", true);
  if (shouldInstallWorkflow) {
    await installWorkflow(process.cwd(), targetRepo);
  }

  // Step 3: Cloudflare Worker Deployment
  logStep(3, 5, "Serverless Edge Tier (Cloudflare Worker)");
  let workerUrl = null;
  let collectedCredentials = {};
  let workerConfig = null;
  const shouldDeployWorker = await promptConfirm("Deploy / Configure Cloudflare Worker edge webhook?", true);
  if (shouldDeployWorker) {
    const workerResult = await deployCloudflareWorker(targetRepo, collectedCredentials);
    workerUrl = workerResult?.workerUrl;
    collectedCredentials = workerResult?.credentials || {};
    workerConfig = {
      wranglerTomlPath: workerResult?.wranglerTomlPath,
      workerDir: workerResult?.workerDir,
    };
  }

  // Step 4: Slack App Manifest
  logStep(4, 5, "Slack App Manifest");
  const shouldCreateManifest = await promptConfirm("Generate 1-click Slack App Manifest JSON?", true);
  if (shouldCreateManifest) {
    await generateSlackManifest(workerUrl, process.cwd());
  }

  // Step 5: Secrets Provisioning
  logStep(5, 5, "Secrets Provisioning (GitHub Actions & Cloudflare Worker)");
  const shouldSetSecrets = await promptConfirm("Provision Slack & GitHub repository secrets now via 'gh' CLI & Wrangler?", true);
  if (shouldSetSecrets) {
    await configureSecrets(targetRepo, collectedCredentials, workerConfig);
  }

  console.log(`\n${c.bold(c.brightGreen("🎉 Setup Complete!"))}`);
  console.log(`You can now trigger autonomous coding tasks directly from Slack (/code) or GitHub Actions!\n`);
}
