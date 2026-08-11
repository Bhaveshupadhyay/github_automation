import subprocess
from typing import Optional
from automation.domain.models import WorkflowEnvironment, GitPRDetails

class GitPRService:
    """Service responsible for executing Git commands and creating Pull Requests."""
    
    def __init__(self, config: WorkflowEnvironment, pr_details: GitPRDetails):
        self.config = config
        self.pr_details = pr_details

    def has_changes(self) -> bool:
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        return bool(res.stdout.strip())

    def create_and_push_branch(self):
        print(f"🌿 Creating Git Branch: {self.pr_details.branch_name}")
        print(f"💬 Using Commit Message: {self.pr_details.commit_message}")

        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        subprocess.run(["git", "checkout", "-b", self.pr_details.branch_name], check=True)
        subprocess.run(["git", "add", "."], check=True)
        subprocess.run(["git", "commit", "-m", self.pr_details.commit_message], check=True)

        remote_url = f"https://x-access-token:{self.config.gh_token}@github.com/{self.config.target_repo}.git"
        subprocess.run(["git", "push", remote_url, self.pr_details.branch_name], check=True)

    def create_pull_request(self) -> Optional[str]:
        cmd = [
            "gh", "pr", "create",
            "--repo", self.config.target_repo,
            "--head", self.pr_details.branch_name,
            "--base", "main",
            "--title", self.pr_details.pr_title,
            "--body", self.pr_details.pr_body
        ]
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode == 0:
            pr_url = res.stdout.strip()
            print(f"🚀 Pull Request created: {pr_url}")
            return pr_url
        else:
            print(f"❌ Failed to create PR: {res.stderr}")
            return None
