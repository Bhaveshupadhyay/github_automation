import readline from "node:readline/promises";
import { stdin as input, stdout as output } from "node:process";

// ANSI escape codes for pure zero-dependency styling
export const colors = {
  reset: "\x1b[0m",
  bold: "\x1b[1m",
  dim: "\x1b[2m",
  italic: "\x1b[3m",
  underline: "\x1b[4m",
  
  // Foreground
  black: "\x1b[30m",
  red: "\x1b[31m",
  green: "\x1b[32m",
  yellow: "\x1b[33m",
  blue: "\x1b[34m",
  magenta: "\x1b[35m",
  cyan: "\x1b[36m",
  white: "\x1b[37m",
  gray: "\x1b[90m",

  // Bright
  brightGreen: "\x1b[92m",
  brightYellow: "\x1b[93m",
  brightBlue: "\x1b[94m",
  brightCyan: "\x1b[96m",
};

export const c = {
  bold: (str) => `${colors.bold}${str}${colors.reset}`,
  dim: (str) => `${colors.dim}${str}${colors.reset}`,
  italic: (str) => `${colors.italic}${str}${colors.reset}`,
  underline: (str) => `${colors.underline}${str}${colors.reset}`,
  black: (str) => `${colors.black}${str}${colors.reset}`,
  red: (str) => `${colors.red}${str}${colors.reset}`,
  green: (str) => `${colors.green}${str}${colors.reset}`,
  yellow: (str) => `${colors.yellow}${str}${colors.reset}`,
  blue: (str) => `${colors.blue}${str}${colors.reset}`,
  magenta: (str) => `${colors.magenta}${str}${colors.reset}`,
  cyan: (str) => `${colors.cyan}${str}${colors.reset}`,
  white: (str) => `${colors.white}${str}${colors.reset}`,
  gray: (str) => `${colors.gray}${str}${colors.reset}`,
  brightGreen: (str) => `${colors.brightGreen}${str}${colors.reset}`,
  brightYellow: (str) => `${colors.brightYellow}${str}${colors.reset}`,
  brightBlue: (str) => `${colors.brightBlue}${str}${colors.reset}`,
  brightCyan: (str) => `${colors.brightCyan}${str}${colors.reset}`,
};

export function renderBanner() {
  console.log(`
${colors.brightCyan}╔═══════════════════════════════════════════════════════════════╗
║                                                               ║
║   ${colors.bold}${colors.white}⚡ AutoPR Slack AI — Autonomous AI Developer${colors.brightCyan}               ║
║   ${colors.dim}${colors.gray}Zero-Clone Edge & GitHub Actions Setup Wizard${colors.brightCyan}               ║
║                                                               ║
╚═══════════════════════════════════════════════════════════════╝${colors.reset}
`);
}

export function logSuccess(msg) {
  console.log(`  ${c.brightGreen("✔")} ${msg}`);
}

export function logInfo(msg) {
  console.log(`  ${c.brightCyan("ℹ")} ${msg}`);
}

export function logWarn(msg) {
  console.log(`  ${c.brightYellow("⚠")} ${msg}`);
}

export function logError(msg) {
  console.log(`  ${c.red("✖")} ${msg}`);
}

export function logStep(num, total, title) {
  console.log(`\n${c.bold(c.cyan(`[${num}/${total}]`))} ${c.bold(title)}`);
}

export async function promptText(question, defaultValue = "") {
  const rl = readline.createInterface({ input, output });
  const hint = defaultValue ? ` ${c.gray(`(${defaultValue})`)}` : "";
  try {
    const answer = await rl.question(`  ${c.bold("?")} ${question}${hint}: `);
    return answer.trim() || defaultValue;
  } finally {
    rl.close();
  }
}

export async function promptSecret(question) {
  const rl = readline.createInterface({ input, output });
  try {
    const answer = await rl.question(`  ${c.bold("?")} ${question} ${c.gray("(input will be hidden in logs)")}: `);
    return answer.trim();
  } finally {
    rl.close();
  }
}

export async function promptConfirm(question, defaultYes = true) {
  const rl = readline.createInterface({ input, output });
  const hint = defaultYes ? "Y/n" : "y/N";
  try {
    const answer = await rl.question(`  ${c.bold("?")} ${question} ${c.gray(`[${hint}]`)}: `);
    const trimmed = answer.trim().toLowerCase();
    if (!trimmed) return defaultYes;
    return trimmed === "y" || trimmed === "yes";
  } finally {
    rl.close();
  }
}

export async function promptSelect(question, choices) {
  const rl = readline.createInterface({ input, output });
  console.log(`\n  ${c.bold("?")} ${question}:`);
  choices.forEach((choice, index) => {
    console.log(`    ${c.cyan(`${index + 1})`)} ${choice.title}${choice.description ? ` ${c.gray(`— ${choice.description}`)}` : ""}`);
  });
  
  try {
    while (true) {
      const answer = await rl.question(`  ${c.gray("Enter choice [1-" + choices.length + "]: ")}`);
      const num = parseInt(answer.trim(), 10);
      if (num >= 1 && num <= choices.length) {
        return choices[num - 1].value;
      }
      console.log(`    ${c.red("Invalid choice, please select between 1 and " + choices.length)}`);
    }
  } finally {
    rl.close();
  }
}
