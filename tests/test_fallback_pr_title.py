"""The PR title used when the model writes no metadata must read like a person wrote it."""
import automation.core  # noqa: F401  Resolves the services' import order first.
from automation.services.gemini_metadata_service import MAX_TITLE_CHARS, fallback_pr_title


def test_uses_the_first_sentence_as_a_conventional_commit():
    title = fallback_pr_title("add admin panel to this. it should be able to view, add, update, delete the post.")

    assert title == "feat: add admin panel to this"


def test_carries_no_tool_or_model_branding():
    title = fallback_pr_title("add admin panel to this.")

    for noise in ("Antigravity", "Patch", "gemini", "🤖"):
        assert noise not in title


def test_drops_the_bot_mention_and_target_repo():
    title = fallback_pr_title("@AutoGit AI target repo: acme/web\nAdd a footer with social links")

    assert title == "feat: add a footer with social links"


def test_long_requests_are_cut_at_a_word_boundary():
    title = fallback_pr_title(
        "Change the Redis cache TTL for trending posts from five minutes to thirty minutes and more"
    )

    assert len(title) <= MAX_TITLE_CHARS
    assert title.endswith("minutes")


def test_an_empty_request_still_gets_a_title():
    assert fallback_pr_title("") == "feat: apply requested changes"
