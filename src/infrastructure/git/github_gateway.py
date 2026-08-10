import os
import json
import time
import shutil
import subprocess
import urllib.request
from src.domain.interfaces import IGitGateway
from src.domain.entities import CodeModification, PullRequestResult
from src.core.exceptions import GitRepositoryError
from src.core.logger import logger

class GitHubGitAdapter(IGitGateway):
    """Adapter for Git local CLI & GitHub REST API operations."""

    def __init__(self, github_token: str, default_repository: str):
        self.github_token = github_token
        self.default_repository = default_repository
        self.target_dir = None

    def prepare_workspace(self, repository: str) -> None:
        target_repo = repository or self.default_repository
        current_repo = os.getenv("GITHUB_REPOSITORY", "")

        if current_repo and current_repo.lower() == target_repo.lower():
            logger.info(f"Already in target repository workspace: {target_repo}")
            return

        logger.info(f"Cloning target repository '{target_repo}' for execution...")
        self.target_dir = os.path.abspath("workspace_target")

        if os.path.exists(self.target_dir):
            shutil.rmtree(self.target_dir)

        remote_url = f"https://x-access-token:{self.github_token}@github.com/{target_repo}.git"
        try:
            subprocess.run(["git", "clone", "--depth", "1", remote_url, self.target_dir], check=True)
            os.chdir(self.target_dir)
            logger.info(f"Switched working directory to target repo workspace: {self.target_dir}")
        except Exception as e:
            raise GitRepositoryError(f"Failed to clone repository '{target_repo}': {e}")

    def _github_api_request(self, endpoint: str, repository: str, method: str = "GET", data: dict = None) -> dict:
        url = f"https://api.github.com/{endpoint}"
        headers = {
            "Authorization": f"token {self.github_token}",
            "Accept": "application/vnd.github.v3+json",
            "User-Agent": "Autonomous-AI-Agent"
        }
        payload = json.dumps(data).encode("utf-8") if data else None
        req = urllib.request.Request(url, data=payload, headers=headers, method=method)
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as e:
            raise GitRepositoryError(f"GitHub API Error [{endpoint}] for repo '{repository}': {e}")

    def apply_and_push_changes(self, modification: CodeModification, repository: str = "") -> str:
        target_repo = repository or self.default_repository
        logger.info(f"Applying file modifications for repository: {target_repo}")

        written_count = 0
        for filepath, content in modification.files.items():
            # Safety check: Prevent IsADirectoryError if LLM passed a directory name as key
            if os.path.isdir(filepath):
                logger.warning(f"Skipping key '{filepath}' because it is a directory name, not a file path.")
                continue

            dir_name = os.path.dirname(filepath)
            if dir_name:
                os.makedirs(dir_name, exist_ok=True)
                
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)
            written_count += 1
            logger.info(f"Updated file: {filepath}")

        if written_count == 0:
            raise GitRepositoryError("No valid file modifications were provided by the AI agent.")

        timestamp = int(time.time())
        branch_name = f"ai-patch-{timestamp}"

        try:
            subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
            subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
            subprocess.run(["git", "checkout", "-b", branch_name], check=True)
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", modification.commit_message], check=True)
            
            remote_url = f"https://x-access-token:{self.github_token}@github.com/{target_repo}.git"
            subprocess.run(["git", "push", remote_url, branch_name], check=True)
            logger.info(f"Successfully pushed branch '{branch_name}' to remote {target_repo}")
            return branch_name
        except Exception as e:
            raise GitRepositoryError(f"Failed to push git branch to {target_repo}: {e}")

    def create_and_merge_pr(self, branch_name: str, commit_message: str, user_prompt: str, repository: str = "", auto_merge: bool = False) -> PullRequestResult:
        target_repo = repository or self.default_repository
        logger.info(f"Opening Pull Request on GitHub for {target_repo}...")

        pr_data = {
            "title": f"🤖 {commit_message}",
            "head": branch_name,
            "base": "main",
            "body": f"Automated PR from Request:\n> {user_prompt}"
        }
        
        pr_res = self._github_api_request(f"repos/{target_repo}/pulls", repository=target_repo, method="POST", data=pr_data)
        pr_number = pr_res["number"]
        pr_url = pr_res["html_url"]

        logger.info(f"Successfully created Pull Request #{pr_number}: {pr_url}")

        if auto_merge:
            logger.info(f"Auto-merge enabled. Merging PR #{pr_number} into main...")
            merge_data = {"commit_title": f"Auto-merged PR #{pr_number}", "merge_method": "squash"}
            self._github_api_request(f"repos/{target_repo}/pulls/{pr_number}/merge", repository=target_repo, method="PUT", data=merge_data)
            logger.info(f"PR #{pr_number} successfully auto-merged!")
            return PullRequestResult(pr_number=pr_number, pr_url=pr_url, branch_name=branch_name, is_merged=True)
        else:
            logger.info(f"Auto-merge is DISABLED. Pull Request #{pr_number} is open and ready for review.")
            return PullRequestResult(pr_number=pr_number, pr_url=pr_url, branch_name=branch_name, is_merged=False)
