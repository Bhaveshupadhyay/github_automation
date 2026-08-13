import os
import json
import logging
import subprocess
from typing import Optional
from automation.domain import WorkflowEnvironment, GitPRDetails
from automation.interfaces.git_pr_interface import IGitPRService

logger = logging.getLogger("automation.git_pr")

EXCLUDED_INSTRUCTION_FILES = [
    ".agents/rules/antigravity-instructions.md",
    "antigravity-instructions.md"
]

class GitPRService(IGitPRService):
    """Service responsible for executing Git commands and creating/updating Pull Requests."""
    
    def __init__(self, config: WorkflowEnvironment, pr_details: GitPRDetails):
        self.config = config
        self.pr_details = pr_details

    def _exclude_instruction_files(self):
        """Unstages and restores antigravity-instructions.md files so they are excluded from PR diffs on target repos."""
        for file_path in EXCLUDED_INSTRUCTION_FILES:
            subprocess.run(["git", "reset", "HEAD", "--", file_path], capture_output=True)
            subprocess.run(["git", "checkout", "--", file_path], capture_output=True)
            # If working on an external target repository, ensure instruction files are cleaned up from working tree
            if os.path.exists(file_path) and self.config.target_repo and "github_automation" not in self.config.target_repo.lower():
                try:
                    os.remove(file_path)
                except Exception:
                    pass

    def has_changes(self) -> bool:
        self._exclude_instruction_files()
        res = subprocess.run(["git", "status", "--porcelain"], capture_output=True, text=True)
        lines = [
            line for line in res.stdout.splitlines()
            if not any(excluded in line for excluded in EXCLUDED_INSTRUCTION_FILES)
        ]
        return bool(lines)

    def create_and_push_branch(self):
        logger.info(f"🌿 Processing Git Branch: {self.pr_details.branch_name}")
        logger.info(f"💬 Using Commit Message: {self.pr_details.commit_message}")

        subprocess.run(["git", "config", "user.name", "github-actions[bot]"], check=True)
        subprocess.run(["git", "config", "user.email", "41898282+github-actions[bot]@users.noreply.github.com"], check=True)
        
        # Check if branch exists remotely
        remote_check = subprocess.run(
            ["git", "ls-remote", "--heads", "origin", self.pr_details.branch_name],
            capture_output=True,
            text=True
        )

        if remote_check.stdout.strip():
            logger.info(f"🔄 Branch '{self.pr_details.branch_name}' already exists remotely. Switching branch using -B...")
            subprocess.run(["git", "fetch", "origin", self.pr_details.branch_name], check=True)
            subprocess.run(["git", "checkout", "-B", self.pr_details.branch_name], check=True)
        else:
            subprocess.run(["git", "checkout", "-b", self.pr_details.branch_name], check=True)

        subprocess.run(["git", "add", "."], check=True)
        self._exclude_instruction_files()
        subprocess.run(["git", "commit", "-m", self.pr_details.commit_message], check=True)

        remote_url = f"https://x-access-token:{self.config.gh_token}@github.com/{self.config.target_repo}.git"
        subprocess.run(["git", "push", "--force", remote_url, self.pr_details.branch_name], check=True)

    def create_pull_request(self) -> Optional[str]:
        # Check if a PR already exists for this branch
        check_pr = subprocess.run(
            ["gh", "pr", "list", "--repo", self.config.target_repo, "--head", self.pr_details.branch_name, "--json", "url"],
            capture_output=True,
            text=True
        )

        if check_pr.returncode == 0 and check_pr.stdout.strip():
            try:
                prs = json.loads(check_pr.stdout.strip())
                if prs and isinstance(prs, list) and "url" in prs[0]:
                    existing_pr_url = prs[0]["url"]
                    logger.info(f"🚀 Updated existing Pull Request for branch '{self.pr_details.branch_name}': {existing_pr_url}")
                    return existing_pr_url
            except Exception:
                pass

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
            logger.info(f"🚀 Pull Request created: {pr_url}")
            return pr_url
        else:
            logger.error(f"❌ Failed to create PR: {res.stderr}")
            return None
