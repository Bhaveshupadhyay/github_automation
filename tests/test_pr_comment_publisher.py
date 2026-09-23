"""Unit tests for GitHubPRCommentPublisher idempotency guarantees."""
from typing import Any, Optional
from urllib.parse import parse_qs, urlparse

import pytest

from automation.services.github_pr_comment_publisher import (
    COMMENT_MARKER,
    MAX_COMMENT_CHARS,
    GitHubPRCommentPublisher,
)

BOT_LOGIN = "qa-preview-bot"


class FakeGitHub:
    """In-memory stand-in for the GitHub issue comments API.

    Models the subset the publisher touches, including pagination, so tests exercise
    the real request-sequencing logic rather than a mocked-out shortcut.
    """

    def __init__(self, bot_login: Optional[str] = BOT_LOGIN, user_endpoint_allowed: bool = True):
        self.comments: list[dict] = []
        self._next_id = 1000
        self.bot_login = bot_login
        self.user_endpoint_allowed = user_endpoint_allowed
        self.calls: list[tuple[str, str]] = []

    def add_comment(self, body: str, login: str = BOT_LOGIN, user_type: str = "Bot") -> dict:
        self._next_id += 1
        comment = {
            "id": self._next_id,
            "body": body,
            "user": {"login": login, "type": user_type},
            "html_url": f"https://github.com/acme/web/pull/42#issuecomment-{self._next_id}",
        }
        self.comments.append(comment)
        return comment

    def request(self, method: str, url: str, payload: Optional[dict] = None) -> Any:
        self.calls.append((method, url))

        if method == "GET" and url.endswith("/user"):
            if not self.user_endpoint_allowed:
                raise RuntimeError("GitHub API GET /user failed (403): Resource not accessible by integration")
            return {"login": self.bot_login}

        if method == "GET" and "/comments" in url:
            # Parse the query properly: a naive `page=(\d+)` regex also matches inside
            # `per_page=100`, which silently returns the wrong page.
            query = parse_qs(urlparse(url).query)
            page = int(query.get("page", ["1"])[0])
            per_page = int(query.get("per_page", ["100"])[0])
            start = (page - 1) * per_page
            return self.comments[start : start + per_page]

        if method == "POST" and "/comments" in url:
            return self.add_comment(payload["body"])

        if method == "PATCH" and "/issues/comments/" in url:
            comment_id = int(url.rstrip("/").split("/")[-1])
            for c in self.comments:
                if c["id"] == comment_id:
                    c["body"] = payload["body"]
                    return c
            raise RuntimeError("GitHub API PATCH failed (404): Not Found")

        if method == "DELETE" and "/issues/comments/" in url:
            comment_id = int(url.rstrip("/").split("/")[-1])
            self.comments = [c for c in self.comments if c["id"] != comment_id]
            return None

        raise AssertionError(f"Unexpected request: {method} {url}")

    @property
    def bot_comments(self) -> list[dict]:
        return [c for c in self.comments if c["body"].lstrip().startswith(COMMENT_MARKER)]


def build_publisher(fake: FakeGitHub, bot_login: Optional[str] = None) -> GitHubPRCommentPublisher:
    publisher = GitHubPRCommentPublisher(token="fake-token", bot_login=bot_login)
    publisher._request = fake.request  # type: ignore[method-assign]
    return publisher


class TestIdempotency:
    """The core Phase 5 guarantee: repeated pushes leave exactly one comment."""

    def test_first_publish_creates_a_comment(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        result = publisher.upsert_comment("acme/web", 42, f"{COMMENT_MARKER}\nrun 1")

        assert result.success
        assert result.created is True
        assert len(fake.bot_comments) == 1

    def test_consecutive_pushes_update_one_comment_in_place(self):
        """Simulates several pushes to the same PR, per the phase verification criteria."""
        fake = FakeGitHub()
        fake.add_comment("Opened this PR.", login="a-developer", user_type="User")
        publisher = build_publisher(fake)

        for run in range(1, 6):
            result = publisher.upsert_comment("acme/web", 42, f"{COMMENT_MARKER}\nrun {run}")
            assert result.success

        assert len(fake.bot_comments) == 1, "Repeated publishes must not accumulate comments"
        assert fake.bot_comments[0]["body"].endswith("run 5"), "Comment must hold the newest result"
        assert len(fake.comments) == 2, "The human's comment must be left untouched"

    def test_subsequent_publish_reports_update_not_create(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        first = publisher.upsert_comment("acme/web", 42, "run 1")
        second = publisher.upsert_comment("acme/web", 42, "run 2")

        assert first.created is True
        assert second.created is False
        assert second.comment_id == first.comment_id


class TestAuthorshipVerification:
    """A human quoting the marker must never have their comment overwritten."""

    def test_human_comment_containing_marker_is_not_adopted(self):
        fake = FakeGitHub()
        quoted = fake.add_comment(
            f"{COMMENT_MARKER}\nWhy does this say passed? The button is still broken.",
            login="a-reviewer",
            user_type="User",
        )
        publisher = build_publisher(fake)

        result = publisher.upsert_comment("acme/web", 42, "run 1")

        assert result.created is True, "Must post its own comment rather than hijack the human's"
        assert quoted["body"].endswith("still broken."), "The human's text must be preserved verbatim"

    def test_other_bot_with_different_login_is_ignored(self):
        fake = FakeGitHub()
        fake.add_comment(f"{COMMENT_MARKER}\nfrom another bot", login="some-other-bot", user_type="Bot")
        publisher = build_publisher(fake, bot_login=BOT_LOGIN)

        result = publisher.upsert_comment("acme/web", 42, "run 1")

        assert result.created is True

    def test_falls_back_to_account_type_when_identity_unavailable(self):
        """A workflow GITHUB_TOKEN cannot call /user, so authorship falls back to type."""
        fake = FakeGitHub(user_endpoint_allowed=False)
        fake.add_comment(f"{COMMENT_MARKER}\nrun 1", login="github-actions[bot]", user_type="Bot")
        publisher = build_publisher(fake)

        result = publisher.upsert_comment("acme/web", 42, "run 2")

        assert result.created is False, "Must recognise a prior bot-authored comment"
        assert len(fake.bot_comments) == 1

    def test_human_comment_ignored_when_identity_unavailable(self):
        fake = FakeGitHub(user_endpoint_allowed=False)
        fake.add_comment(f"{COMMENT_MARKER}\nquoted by a person", login="a-reviewer", user_type="User")
        publisher = build_publisher(fake)

        result = publisher.upsert_comment("acme/web", 42, "run 1")

        assert result.created is True


class TestPagination:
    """A first-page-only lookup silently posts duplicates on busy pull requests."""

    def test_finds_bot_comment_beyond_the_first_page(self):
        fake = FakeGitHub()
        for i in range(120):
            fake.add_comment(f"chatter {i}", login="a-developer", user_type="User")
        fake.add_comment(f"{COMMENT_MARKER}\nrun 1")
        for i in range(30):
            fake.add_comment(f"more chatter {i}", login="a-developer", user_type="User")

        publisher = build_publisher(fake)
        result = publisher.upsert_comment("acme/web", 42, f"{COMMENT_MARKER}\nrun 2")

        assert result.created is False, "Must find the comment on page 2 instead of duplicating it"
        assert len(fake.bot_comments) == 1

    def test_stops_paging_on_a_short_page(self):
        fake = FakeGitHub()
        for i in range(5):
            fake.add_comment(f"chatter {i}", login="a-developer", user_type="User")
        publisher = build_publisher(fake)

        publisher.find_existing_comment("acme/web", 42)

        comment_pages = [c for c in fake.calls if c[0] == "GET" and "/comments" in c[1]]
        assert len(comment_pages) == 1, "A partial page means there is nothing more to fetch"


class TestConcurrencyBackstop:
    """Two racing runs can both create a comment before Phase 6 cancellation applies."""

    def test_duplicates_are_collapsed_to_the_newest(self):
        fake = FakeGitHub()
        stale = fake.add_comment(f"{COMMENT_MARKER}\nrun A")
        newest = fake.add_comment(f"{COMMENT_MARKER}\nrun B")
        publisher = build_publisher(fake)

        result = publisher.upsert_comment("acme/web", 42, f"{COMMENT_MARKER}\nrun C")

        assert result.duplicates_removed == 1
        assert result.comment_id == newest["id"]
        assert len(fake.bot_comments) == 1
        assert all(c["id"] != stale["id"] for c in fake.comments)


class TestBodyHandling:
    def test_marker_is_added_when_missing(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        publisher.upsert_comment("acme/web", 42, "a body with no marker")

        assert fake.comments[0]["body"].startswith(COMMENT_MARKER)

    def test_marker_is_not_duplicated(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        publisher.upsert_comment("acme/web", 42, f"{COMMENT_MARKER}\nbody")

        assert fake.comments[0]["body"].count(COMMENT_MARKER) == 1

    def test_oversized_body_is_truncated_below_the_api_limit(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        publisher.upsert_comment("acme/web", 42, "x" * (MAX_COMMENT_CHARS + 5000))

        assert len(fake.comments[0]["body"]) <= MAX_COMMENT_CHARS
        assert fake.comments[0]["body"].endswith("_(report truncated)_")


class TestFailureHandling:
    def test_missing_token_reports_failure_without_raising(self):
        publisher = GitHubPRCommentPublisher(token="")

        result = publisher.upsert_comment("acme/web", 42, "body")

        assert result.success is False
        assert "token" in (result.error_message or "").lower()

    def test_api_error_while_reading_is_reported(self):
        fake = FakeGitHub()
        publisher = build_publisher(fake)

        def boom(method, url, payload=None):
            raise RuntimeError("GitHub API GET failed (502): Bad Gateway")

        publisher._request = boom  # type: ignore[method-assign]
        result = publisher.upsert_comment("acme/web", 42, "body")

        assert result.success is False
        assert "502" in (result.error_message or "")
