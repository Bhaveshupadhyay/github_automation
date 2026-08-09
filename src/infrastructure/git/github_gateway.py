import os
import json
import time
import subprocess
import urllib.request
from src.domain.interfaces import IGitGateway
from src.domain.entities import CodeModification, PullRequestResult
from src.core.exceptions import GitRepositoryError

class GitHubGitAdapter(IGitGateway):
    """Adapter for Git local CLI & GitHub REST API operations."""

    def __init__(self, github_token: str, repository: str):
        self.github_token = github_token
        self.repository = repository

    def _github_api_request(self, endpoint: str, method: str = "GET", data: dict = None) -> dict:
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
            raise GitRepositoryError(f"GitHub API Error [{endpoint}]: {e}")

    def apply_and_push_changes(self, modification: CodeModification) -> str:
        for filepath, content in modification.files.items():
            if os.path.dirname(filepath):
                os.makedirs(os.path.dirname(filepath), exist_ok=True)
            with open(filepath, "w", encoding="utf-8") as f:
                f.write(content)

        timestamp = int(time.time())
        branch_name = f"ai-patch-{timestamp}"

        try:
            subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
            subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
            subprocess.run(["git", "checkout", "-b", branch_name], check=True)
            subprocess.run(["git", "add", "."], check=True)
            subprocess.run(["git", "commit", "-m", modification.commit_message], check=True)
            
            remote_url = f"https://x-access-token:{self.github_token}@github.com/{self.repository}.git"
            subprocess.run(["git", "push", remote_url, branch_name], check=True)
            return branch_name
        except Exception as e:
            raise GitRepositoryError(f"Failed to push git branch: {e}")

    def create_and_merge_pr(self, branch_name: str, commit_message: str, user_prompt: str) -> PullRequestResult:
        pr_data = {
            "title": f"🤖 {commit_message}",
            "head": branch_name,
            "base": "main",
            "body": f"Automated PR from Request:\n> {user_prompt}"
        }
        
        pr_res = self._github_api_request(f"repos/{self.repository}/pulls", method="POST", data=pr_data)
        pr_number = pr_res["number"]
        pr_url = pr_res["html_url"]

        merge_data = {"commit_title": f"Auto-merged PR #{pr_number}", "merge_method": "squash"}
        self._github_api_request(f"repos/{self.repository}/pulls/{pr_number}/merge", method="PUT", data=merge_data)

        return PullRequestResult(
            pr_number=pr_number,
            pr_url=pr_url,
            branch_name=branch_name,
            is_merged=True
        )
