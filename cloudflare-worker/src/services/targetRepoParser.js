const SLUG = "[A-Za-z0-9_.-]+\\/[A-Za-z0-9_.-]+";
// Slack wraps links as <url|label>; people wrap slugs in quotes or backticks.
const WRAPPED = "[<`'\"‘’“”]*(?:(?:https?:\\/\\/)?(?:www\\.)?github\\.com\\/)?";

// "target repo: owner/repo", "target repository owner/repo", "repo = owner/repo".
// A bare "repo" needs the colon, so prose like "the repo and/or docs" is not a label.
const LABELED_PATTERN = new RegExp(
  `\\b(?:target\\s+repo(?:sitory)?\\s*[:=]?|repo(?:sitory)?\\s*[:=])\\s*${WRAPPED}(${SLUG})[^\\s]*`,
  "i"
);
// "owner/repo do something" (the original `/code [owner/repo] <prompt>` form), or a bare
// "owner/repo" answering the bot's repository question.
const LEADING_PATTERN = new RegExp(`^${WRAPPED}(${SLUG})[^\\s]*(?=\\s|$)`);
// A GitHub link anywhere in the message.
const GITHUB_URL_PATTERN = new RegExp(`https?:\\/\\/(?:www\\.)?github\\.com\\/(${SLUG})`, "i");

// Slash-joined words that read as owner/repo (mirrors PROSE_SLASH_BLACKLIST in automation/domain/environment.py).
const PROSE_SLASHES = new Set([
  "documentation/instructions", "create/update", "add/update", "update/create",
  "delete/remove", "pull/merge", "commit/push", "fetch/pull", "and/or", "true/false",
  "read/write", "input/output", "import/export", "client/server", "master/slave",
  "main/master", "ci/cd", "next.js/react"
]);

/**
 * Trims what a slug capture can pick up around the name: a `.git` suffix and sentence punctuation.
 * @param {string} slug
 */
function cleanSlug(slug) {
  const [owner, name] = slug.split("/");
  return `${owner}/${name.replace(/\.git$/i, "").replace(/\.+$/, "")}`;
}

/**
 * Finds the repository a Slack request targets and the prompt without it.
 * Returns an empty `repo` when the message names none, so the caller asks for one.
 *
 * @param {string} text
 * @returns {{ repo: string, prompt: string }}
 */
export function parseTargetRepo(text) {
  const message = text.trim();

  for (const pattern of [LABELED_PATTERN, LEADING_PATTERN]) {
    const match = message.match(pattern);
    if (match && !PROSE_SLASHES.has(match[1].toLowerCase())) {
      const prompt = message.replace(match[0], " ").replace(/^[\s,;:.-]+/, "");
      return { repo: cleanSlug(match[1]), prompt: prompt.replace(/\s+/g, " ").trim() };
    }
  }

  // A link is part of the request ("fix the bug in <url>"), so it stays in the prompt.
  const url = message.match(GITHUB_URL_PATTERN);
  return { repo: url ? cleanSlug(url[1]) : "", prompt: message.replace(/\s+/g, " ") };
}
