import { c, renderBanner } from "./ui.js";
import { runInitWizard } from "./commands/init.js";
import { runHealthCheck } from "./commands/check.js";
import { installWorkflow } from "./commands/workflow.js";
import { deployCloudflareWorker } from "./commands/deployWorker.js";
import { configureSecrets } from "./commands/secrets.js";
import { generateSlackManifest } from "./commands/manifest.js";

function printHelp() {
  renderBanner();
  console.log(`
${c.bold("Usage:")}
  npx autopr-slack [command] [options]

${c.bold("Commands:")}
  ${c.brightGreen("init")}             Run the full interactive setup wizard (Default)
  ${c.brightGreen("workflow")}         Install AutoPR GitHub Actions workflow in current repository
  ${c.brightGreen("deploy-worker")}    Deploy/update the serverless Cloudflare Worker edge webhook
  ${c.brightGreen("secrets")}          Configure GitHub repository secrets automatically via gh CLI
  ${c.brightGreen("manifest")}         Generate 1-click Slack App Manifest JSON file
  ${c.brightGreen("check")}            Run environment diagnostics & credential preflight checks

${c.bold("Options:")}
  -h, --help        Show help message
  -v, --version     Show version

${c.bold("Examples:")}
  $ npx autopr-slack init
  $ npx autopr-slack workflow
  $ npx autopr-slack manifest
`);
}

export async function runCli(args = []) {
  const cmd = args[0] || "init";

  switch (cmd) {
    case "init":
      await runInitWizard();
      break;

    case "workflow":
      renderBanner();
      await installWorkflow(process.cwd());
      break;

    case "deploy-worker":
    case "worker":
      renderBanner();
      await deployCloudflareWorker();
      break;

    case "secrets":
      renderBanner();
      await configureSecrets();
      break;

    case "manifest":
      renderBanner();
      await generateSlackManifest();
      break;

    case "check":
    case "doctor":
      renderBanner();
      await runHealthCheck();
      break;

    case "-h":
    case "--help":
    case "help":
      printHelp();
      break;

    case "-v":
    case "--version":
      console.log("autopr-slack v0.1.0");
      break;

    default:
      console.log(`\n${c.red("Unknown command:")} ${cmd}`);
      printHelp();
      process.exit(1);
  }
}
