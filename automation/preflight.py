import os
import sys
import logging
import urllib.request
import urllib.error
from typing import Optional

from automation.domain import extract_target_repo, WorkflowEnvironment
from automation.services.slack_history_service import SlackHistoryService

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("automation.preflight")

def resolve_target_repo() -> str:
    """Pre-flight logic executed on GitHub Actions runner to resolve target repository before cloning workspace."""
    user_prompt = os.getenv("USER_PROMPT", "").strip()
    payload_target = os.getenv("PAYLOAD_TARGET", "").strip()
    input_target = os.getenv("INPUT_TARGET", "").strip()
    slack_thread_ts = os.getenv("SLACK_THREAD", "").strip()
    gh_token = os.getenv("GH_TOKEN", "").strip()

    logger.info("Resolving Target Repository for workflow execution...")

    # Priority 1: Extract explicit target repository from prompt text (e.g. bhaveshupadhyay/culture_box)
    candidate_prompt_repo = extract_target_repo(user_prompt, "")

    # If prompt is a thread clarification (or slack_thread_ts is present), inspect root message (Turn 1) from Slack!
    if not candidate_prompt_repo and slack_thread_ts:
        try:
            config = WorkflowEnvironment()
            history_service = SlackHistoryService(config)
            
            # Step A: Check Turn 1 (the initial root user message)
            first_msg = history_service.fetch_first_message_text()
            if first_msg:
                candidate_prompt_repo = extract_target_repo(first_msg, "")
                
            # Step B: Fallback to full thread history if root message didn't contain target repo
            if not candidate_prompt_repo:
                fetched_history = history_service.fetch_thread_history()
                if fetched_history:
                    candidate_prompt_repo = extract_target_repo(fetched_history, "")
        except Exception as e:
            logger.debug(f"Preflight Slack thread lookup exception: {e}")

    if candidate_prompt_repo:
        logger.info(f"Candidate target repo found in prompt/thread: '{candidate_prompt_repo}'")
        if gh_token:
            try:
                url = f"https://api.github.com/repos/{candidate_prompt_repo}"
                req = urllib.request.Request(
                    url,
                    headers={
                        "Authorization": f"Bearer {gh_token}",
                        "Accept": "application/vnd.github+json"
                    }
                )
                with urllib.request.urlopen(req, timeout=5) as resp:
                    if resp.status == 200:
                        logger.info(f"Validated Target Repo '{candidate_prompt_repo}' via GitHub API. Overriding payload target.")
                        return candidate_prompt_repo
            except urllib.error.HTTPError as err:
                if err.code == 404:
                    logger.warning(f"Candidate repo '{candidate_prompt_repo}' does not exist on GitHub (HTTP 404).")
                else:
                    logger.info(f"GitHub API returned HTTP {err.code} for candidate '{candidate_prompt_repo}'. Accepting candidate.")
                    return candidate_prompt_repo
            except Exception as e:
                logger.info(f"GitHub API check inconclusive ({e}). Accepting candidate '{candidate_prompt_repo}'.")
                return candidate_prompt_repo
        else:
            logger.info(f"Target Repo extracted from prompt (No GH_TOKEN available): '{candidate_prompt_repo}'")
            return candidate_prompt_repo

    # Priority 2: Manual workflow input target
    if input_target:
        logger.info(f"Using Manual Input Target Repository: '{input_target}'")
        return input_target

    # Priority 3: Webhook payload target fallback ONLY if request is NOT from a Slack thread
    if payload_target and not slack_thread_ts:
        logger.info(f"Using Webhook Payload Target Repository: '{payload_target}'")
        return payload_target

    logger.info("No target repository found in prompt, thread history, or manual input.")
    return ""

def main() -> None:
    resolved_target = resolve_target_repo()
    
    # Export resolved target repo to GitHub Actions outputs file
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output:
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"target_repo={resolved_target}\n")
            logger.info(f"Exported target_repo='{resolved_target}' to GITHUB_OUTPUT file")
        except Exception as e:
            logger.error(f"Failed to write to GITHUB_OUTPUT: {e}")

    print(f"PREFLIGHT_TARGET_REPO={resolved_target}")

if __name__ == "__main__":
    main()
