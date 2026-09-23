"""Idempotent GitHub pull request comment publisher."""
import json
import logging
import os
import urllib.error
import urllib.request
from typing import Any, Optional

from automation.interfaces.pr_comment_interface import IPRCommentPublisher, PRCommentResult

logger = logging.getLogger("automation.pr_comment")

GITHUB_API_BASE = "https://api.github.com"

# Invisible in rendered markdown, greppable in the raw body. This is how the bot
# recognises its own prior comment across workflow runs, since a runner keeps no state.
COMMENT_MARKER = "<!-- qa-preview-bot -->"

# GitHub rejects comment bodies longer than this.
MAX_COMMENT_CHARS = 65536

COMMENTS_PER_PAGE = 100

# Guards against an unbounded loop if the API keeps returning full pages.
MAX_COMMENT_PAGES = 20

REQUEST_TIMEOUT_SECONDS = 15


class GitHubPRCommentPublisher(IPRCommentPublisher):
    """Maintains exactly one QA result comment per pull request.

    Posting a fresh comment on every push buries the conversation under stale results,
    sends a notification per push, and leaves reviewers to work out which red badge is
    current. This publisher finds its previous comment and edits it in place instead.
    """

    def __init__(
        self,
        token: Optional[str] = None,
        api_base: str = GITHUB_API_BASE,
        bot_login: Optional[str] = None,
        marker: str = COMMENT_MARKER,
    ):
        self._token = token or os.getenv("GH_TOKEN") or os.getenv("GITHUB_TOKEN") or ""
        self._api_base = api_base.rstrip("/")
        self._bot_login = bot_login or os.getenv("QA_BOT_LOGIN") or None
        self._marker = marker
        self._identity_resolved = False
        self._identity_verified = bool(self._bot_login)

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "qa-preview-bot",
            "Content-Type": "application/json",
        }

    def _request(self, method: str, url: str, payload: Optional[dict] = None) -> Any:
        """Issue one authenticated GitHub API call."""
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        req = urllib.request.Request(url, data=data, headers=self._headers(), method=method)
        try:
            with urllib.request.urlopen(req, timeout=REQUEST_TIMEOUT_SECONDS) as resp:
                raw = resp.read().decode("utf-8")
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"GitHub API {method} {url} failed ({e.code}): {detail}") from e
        except urllib.error.URLError as e:
            raise RuntimeError(f"GitHub API {method} {url} unreachable: {e.reason}") from e

    def _resolve_bot_login(self) -> Optional[str]:
        """Determine the authenticated account's login, if the token permits it.

        A workflow's `GITHUB_TOKEN` is not allowed to call `/user`, so this frequently
        returns None. Authorship is then checked by account type instead.
        """
        if self._identity_resolved:
            return self._bot_login
        self._identity_resolved = True

        if self._bot_login:
            self._identity_verified = True
            return self._bot_login

        try:
            user = self._request("GET", f"{self._api_base}/user")
            if isinstance(user, dict) and user.get("login"):
                self._bot_login = user["login"]
                self._identity_verified = True
                logger.debug(f"Resolved bot identity: {self._bot_login}")
                return self._bot_login
        except RuntimeError as e:
            logger.debug(f"Could not resolve bot identity via /user ({e}).")

        # A workflow GITHUB_TOKEN cannot call /user, but comments it authors always
        # belong to this account, so the identity is still known exactly.
        if os.getenv("GITHUB_ACTIONS") == "true":
            self._bot_login = "github-actions[bot]"
            self._identity_verified = True
            logger.debug("Assuming the GitHub Actions bot identity for comment matching.")
            return self._bot_login

        logger.warning(
            "Could not verify this bot's identity. Falling back to matching any machine "
            "account, and duplicate removal is disabled to avoid deleting another bot's comment. "
            "Set QA_BOT_LOGIN to restore exact matching."
        )
        return None

    def _is_own_comment(self, comment: dict) -> bool:
        """Whether this comment is the bot's own prior report.

        The marker alone is not sufficient. A reviewer who quotes the bot's comment
        reproduces the marker in their own body, and matching on it would silently
        overwrite what that person wrote.
        """
        body = (comment.get("body") or "").lstrip()
        if not body.startswith(self._marker):
            return False

        user = comment.get("user") or {}
        login = user.get("login")
        known_login = self._resolve_bot_login()

        if known_login:
            return login == known_login
        # Identity unavailable: accept only machine accounts, which excludes humans.
        return user.get("type") == "Bot"

    def _iter_comments(self, repo: str, pr_number: int) -> list[dict]:
        """Fetch every comment on the pull request, following pagination.

        On a long-lived PR the bot's comment is often not on the first page. A
        first-page-only lookup would conclude no comment exists and post a duplicate.
        """
        comments: list[dict] = []
        exhausted = False
        for page in range(1, MAX_COMMENT_PAGES + 1):
            url = (
                f"{self._api_base}/repos/{repo}/issues/{pr_number}/comments"
                f"?per_page={COMMENTS_PER_PAGE}&page={page}"
            )
            batch = self._request("GET", url)
            if not isinstance(batch, list) or not batch:
                exhausted = True
                break
            comments.extend(batch)
            if len(batch) < COMMENTS_PER_PAGE:
                exhausted = True
                break

        if not exhausted:
            # Only reachable on a pull request with more comments than the cap allows.
            # Say so explicitly: the alternative is silently posting a duplicate.
            logger.warning(
                f"Stopped reading comments at the {MAX_COMMENT_PAGES}-page cap "
                f"({len(comments)} comments). If the QA comment lies beyond this point it "
                f"will not be found and a duplicate may be posted."
            )
        return comments

    def find_existing_comment(self, repo: str, pr_number: int) -> Optional[dict]:
        """Return the bot's most recent prior comment on this PR, or None."""
        matches = self._find_all_own_comments(repo, pr_number)
        return matches[-1] if matches else None

    def _find_all_own_comments(self, repo: str, pr_number: int) -> list[dict]:
        """All of the bot's comments, oldest first.

        More than one can exist if two workflow runs raced before Phase 6's
        cancel-in-progress took effect.
        """
        return [c for c in self._iter_comments(repo, pr_number) if self._is_own_comment(c)]

    def _collapse_duplicates(self, repo: str, own: list[dict]) -> int:
        """Delete all but the newest of the bot's comments.

        Skipped when authorship could not be verified: deleting a comment that merely
        looks like ours, on the strength of an unverified match, is worse than leaving
        a duplicate behind.
        """
        if len(own) <= 1:
            return 0
        if not self._identity_verified:
            logger.warning(
                f"Found {len(own)} comments matching the marker but could not verify authorship. "
                f"Leaving them in place rather than risk deleting another account's comment."
            )
            return 0

        removed = 0
        for stale in own[:-1]:
            if self._delete_comment(repo, stale["id"]):
                removed += 1
        return removed

    def _collapse_after_create(self, repo: str, pr_number: int, created_id: Optional[int]) -> int:
        """Remove any comment a racing run created alongside the one just posted.

        The comment this call created is always kept, so both racing runs converge on a
        single comment regardless of which one re-reads first.
        """
        if created_id is None or not self._identity_verified:
            return 0
        try:
            own = self._find_all_own_comments(repo, pr_number)
        except RuntimeError as e:
            logger.debug(f"Could not re-read comments after creating one: {e}")
            return 0

        removed = 0
        for other in own:
            if other["id"] != created_id and self._delete_comment(repo, other["id"]):
                logger.info(f"Removed a comment created concurrently by another run ({other['id']}).")
                removed += 1
        return removed

    def _delete_comment(self, repo: str, comment_id: int) -> bool:
        try:
            self._request("DELETE", f"{self._api_base}/repos/{repo}/issues/comments/{comment_id}")
            return True
        except RuntimeError as e:
            logger.warning(f"Could not delete duplicate comment {comment_id}: {e}")
            return False

    def upsert_comment(self, repo: str, pr_number: int, body: str) -> PRCommentResult:
        """Edit the bot's existing comment, or create it if absent."""
        if not self._token:
            return PRCommentResult(
                success=False,
                error_message="No GitHub token available (set GH_TOKEN or GITHUB_TOKEN).",
            )

        if not body.lstrip().startswith(self._marker):
            body = f"{self._marker}\n{body}"

        if len(body) > MAX_COMMENT_CHARS:
            logger.warning(
                f"Comment body is {len(body)} chars, exceeding GitHub's {MAX_COMMENT_CHARS} limit. Truncating."
            )
            suffix = "\n\n_(report truncated)_"
            body = body[: MAX_COMMENT_CHARS - len(suffix)] + suffix

        # Resolve identity before scanning, so the deletion guard below reflects whether
        # authorship could actually be verified.
        self._resolve_bot_login()

        try:
            existing = self._find_all_own_comments(repo, pr_number)
        except RuntimeError as e:
            return PRCommentResult(success=False, error_message=f"Could not read PR comments: {e}")

        duplicates_removed = self._collapse_duplicates(repo, existing)

        try:
            if existing:
                target = existing[-1]
                updated = self._request(
                    "PATCH",
                    f"{self._api_base}/repos/{repo}/issues/comments/{target['id']}",
                    {"body": body},
                )
                logger.info(f"Updated existing QA comment {target['id']} on {repo}#{pr_number}")
                return PRCommentResult(
                    comment_id=target["id"],
                    comment_url=(updated or {}).get("html_url") or target.get("html_url"),
                    created=False,
                    duplicates_removed=duplicates_removed,
                    success=True,
                )

            created = self._request(
                "POST",
                f"{self._api_base}/repos/{repo}/issues/{pr_number}/comments",
                {"body": body},
            )
            created_id = (created or {}).get("id")
            logger.info(f"Created QA comment on {repo}#{pr_number}")

            # Read-then-create is not atomic: a concurrent run can pass the same
            # "no comment exists" check and post its own. Re-reading after the write
            # restores the one-comment invariant by the time this call returns.
            duplicates_removed += self._collapse_after_create(repo, pr_number, created_id)

            return PRCommentResult(
                comment_id=created_id,
                comment_url=(created or {}).get("html_url"),
                created=True,
                duplicates_removed=duplicates_removed,
                success=True,
            )
        except RuntimeError as e:
            return PRCommentResult(
                success=False,
                duplicates_removed=duplicates_removed,
                error_message=str(e),
            )
