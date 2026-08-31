#!/usr/bin/env node

/**
 * AutoPR Slack AI - CLI Entrypoint
 * Invoked via: npx autopr-slack [command]
 */

import { runCli } from "../cli/index.js";

runCli(process.argv.slice(2)).catch((err) => {
  console.error("\n❌ Fatal Error:", err.message || err);
  process.exit(1);
});
