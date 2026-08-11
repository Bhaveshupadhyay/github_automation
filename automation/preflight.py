import os
import sys
import logging
import urllib.request
from typing import Optional

from automation.domain.models import extract_target_repo

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("automation.preflight")

def resolve_target_repo() -> str:
    """Pre-flight logic executed on GitHub Actions runner to resolve target repository before cloning workspace."""
    user_prompt = os.getenv("USER_PROMPT", "").strip()
    payload_target = os.getenv("PAYLOAD_TARGET", "").strip()
    input_target = os.getenv("INPUT_TARGET", "").strip()
    gh_token = os.getenv("GH_TOKEN", "").strip()

    logger.info(f"📌 [PRE-FLIGHT] Resolving Target Repository for prompt: '{user_prompt[:80]}...'")

    # Priority 1: Extract explicit target repository from prompt text (e.g. bhaveshupadhyay/culture_box)
    candidate_prompt_repo = extract_target_repo(user_prompt, "")
    
    if candidate_prompt_repo:
        logger.info(f"🔍 Candidate target repo found in prompt: '{candidate_prompt_repo}'")
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
                        logger.info(f"🎯 Validated Target Repo '{candidate_prompt_repo}' via GitHub API. Overriding payload target.")
                        return candidate_prompt_repo
            except Exception as e:
                logger.warning(f"⚠️ Candidate repo '{candidate_prompt_repo}' from prompt failed GitHub API validation: {e}")
        else:
            logger.info(f"🎯 Target Repo extracted from prompt (No GH_TOKEN available for API validation): '{candidate_prompt_repo}'")
            return candidate_prompt_repo

    # Priority 2: Manual workflow input target
    if input_target:
        logger.info(f"🎯 Using Manual Input Target Repository: '{input_target}'")
        return input_target

    # Priority 3: Webhook payload target fallback
    if payload_target:
        logger.info(f"🎯 Using Webhook Payload Target Repository: '{payload_target}'")
        return payload_target

    logger.info("⚠️ No target repository found in prompt, input, or payload.")
    return ""

def main() -> None:
    resolved_target = resolve_target_repo()
    
    # Export resolved target repo to GitHub Actions outputs file
    github_output = os.getenv("GITHUB_OUTPUT")
    if github_output and os.path.exists(os.path.dirname(github_output)):
        try:
            with open(github_output, "a", encoding="utf-8") as f:
                f.write(f"target_repo={resolved_target}\n")
            logger.info(f"✅ Exported target_repo='{resolved_target}' to $GITHUB_OUTPUT")
        except Exception as e:
            logger.error(f"Failed to write to GITHUB_OUTPUT: {e}")

    print(f"PREFLIGHT_TARGET_REPO={resolved_target}")

if __name__ == "__main__":
    main()
