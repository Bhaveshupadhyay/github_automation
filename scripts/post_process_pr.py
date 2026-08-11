import os
import re
import sys
import json
import shutil
import subprocess
import urllib.request
import urllib.parse
from typing import Optional

try:
    from pydantic import BaseModel, Field
    HAS_PYDANTIC = True
except ImportError:
    HAS_PYDANTIC = False
    from dataclasses import dataclass, field

# ==============================================================================
# Domain Models (Clean Architecture)
# ==============================================================================

if HAS_PYDANTIC:
    class WorkflowEnvironment(BaseModel):
        """Pydantic model representing environment configuration passed from GitHub Actions."""
        gh_token: str = Field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
        slack_token: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
        slack_channel: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
        slack_thread_ts: Optional[str] = Field(default_factory=lambda: os.getenv("SLACK_THREAD"))
        target_repo: str = Field(default_factory=lambda: os.getenv("TARGET_REPO", ""))
        user_prompt: str = Field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
        model_name: str = Field(default_factory=lambda: os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"))
        effort_val: str = Field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
        execution_log_path: str = Field(default="../agy_execution.log")

    class GitPRDetails(BaseModel):
        """Pydantic model holding branch, commit message, and PR information."""
        branch_name: str
        commit_message: str
        pr_title: str
        pr_body: str
else:
    @dataclass
    class WorkflowEnvironment:
        gh_token: str = field(default_factory=lambda: os.getenv("GH_TOKEN", ""))
        slack_token: Optional[str] = field(default_factory=lambda: os.getenv("SLACK_TOKEN"))
        slack_channel: Optional[str] = field(default_factory=lambda: os.getenv("SLACK_CHANNEL"))
        slack_thread_ts: Optional[str] = field(default_factory=lambda: os.getenv("SLACK_THREAD"))
        target_repo: str = field(default_factory=lambda: os.getenv("TARGET_REPO", ""))
        user_prompt: str = field(default_factory=lambda: os.getenv("USER_PROMPT", ""))
        model_name: str = field(default_factory=lambda: os.getenv("MODEL_NAME", "gemini-3.5-flash-lite"))
        effort_val: str = field(default_factory=lambda: os.getenv("EFFORT_VAL", "high"))
        execution_log_path: str = "../agy_execution.log"

    @dataclass
    class GitPRDetails:
        branch_name: str
        commit_message: str
        pr_title: str
        pr_body: str

# ==============================================================================
# Service Layer (Clean Architecture)
# ==============================================================================

class WorkspaceCleanupService:
    """Service responsible for stripping temporary files so they are excluded from PR diffs."""
    
    @staticmethod
    def cleanup_unwanted_files():
        print("🧹 Cleaning up injected .agents, rules, skills, and graphify files...")
        unwanted_paths = [".agents", "graphify-out", "graphify_context.txt"]
        
        for path in unwanted_paths:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        
        subprocess.run(["git", "checkout", "--", ".agents"], capture_output=True, text=True)

class LogParserService:
    """Service responsible for extracting SUGGESTED_BRANCH & SUGGESTED_COMMIT tags from agy logs."""
    
    def __init__(self, log_path: str, prompt: str, model_name: str, effort_val: str):
        self.log_path = log_path
        self.prompt = prompt
        self.model_name = model_name
        self.effort_val = effort_val

    def parse_details(self) -> GitPRDetails:
        suggested_branch = None
        suggested_commit = None
        
        if os.path.exists(self.log_path):
            with open(self.log_path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
                
                branch_matches = re.findall(r"SUGGESTED_BRANCH:\s*([^\n\r]+)", content)
                if branch_matches:
                    raw_branch = branch_matches[-1].strip()
                    suggested_branch = re.sub(r"[^a-zA-Z0-9_.-]", "-", raw_branch.lower())
                
                commit_matches = re.findall(r"SUGGESTED_COMMIT:\s*([^\n\r]+)", content)
                if commit_matches:
                    suggested_commit = commit_matches[-1].strip()

        # Failsafe fallback logic if agy did not output custom tags
        if not suggested_branch:
            clean_slug = re.sub(r"[^a-z0-9]", "-", self.prompt.lower())
            clean_slug = re.sub(r"-+", "-", clean_slug).strip("-")[:35]
            timestamp = int(subprocess.check_output(["date", "+%s"]).decode().strip())
            suggested_branch = f"feat/{clean_slug}-{timestamp}"

        if not suggested_commit:
            suggested_commit = f"🤖 Antigravity AI Patch ({self.model_name}): {self.prompt}"

        pr_title = suggested_commit
        pr_body = (
            f"Automated PR generated by Google Antigravity Agent Engine.\n\n"
            f"Model: `{self.model_name}`\n"
            f"Reasoning Effort: `{self.effort_val}`\n"
            f"Prompt: {self.prompt}\n\n"
            f"👀 Please review and merge when ready!"
        )

        return GitPRDetails(
            branch_name=suggested_branch,
            commit_message=suggested_commit,
            pr_title=pr_title,
            pr_body=pr_body
        )

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

class NotificationService:
    """Service responsible for sending interactive notifications to Slack."""
    
    def __init__(self, config: WorkflowEnvironment, pr_details: GitPRDetails):
        self.config = config
        self.pr_details = pr_details

    def send_slack_notification(self, pr_url: str):
        if not self.config.slack_token or not self.config.slack_channel:
            print("ℹ️ Slack notification skipped (SLACK_TOKEN or SLACK_CHANNEL not set).")
            return

        payload = {
            "channel": self.config.slack_channel,
            "text": (
                f"🚀 *Pull Request Created & Ready for Review!*\n\n"
                f"📦 *Repository:* `{self.config.target_repo}`\n"
                f"🧠 *Model:* `{self.config.model_name}` (Effort: `{self.config.effort_val}`)\n"
                f"📌 *Prompt:* `{self.config.user_prompt}`\n"
                f"🔗 *PR Link:* <{pr_url}|View Pull Request>\n\n"
                f"👀 Please review and merge when ready!"
            )
        }
        if self.config.slack_thread_ts:
            payload["thread_ts"] = self.config.slack_thread_ts

        req = urllib.request.Request(
            "https://slack.com/api/chat.postMessage",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.config.slack_token}",
                "Content-Type": "application/json; charset=utf-8"
            }
        )

        try:
            with urllib.request.urlopen(req) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                if result.get("ok"):
                    print("✅ Slack notification posted successfully!")
                else:
                    print(f"⚠️ Slack API error: {result.get('error')}")
        except Exception as e:
            print(f"❌ Error sending Slack notification: {e}")

# ==============================================================================
# Application Orchestrator
# ==============================================================================

def main():
    try:
        config = WorkflowEnvironment()
    except Exception as e:
        print(f"❌ Invalid Environment Configuration: {e}")
        sys.exit(1)

    # 1. Clean up workspace unwanted files
    WorkspaceCleanupService.cleanup_unwanted_files()

    # 2. Parse logs & build PR domain details
    parser = LogParserService(
        log_path=config.execution_log_path,
        prompt=config.user_prompt,
        model_name=config.model_name,
        effort_val=config.effort_val
    )
    pr_details = parser.parse_details()

    # 3. Handle Git & PR creation
    git_service = GitPRService(config, pr_details)
    if not git_service.has_changes():
        print("ℹ️ No file changes were produced by the agent.")
        return

    git_service.create_and_push_branch()
    pr_url = git_service.create_pull_request()

    # 4. Notify Slack if PR was created
    if pr_url:
        notifier = NotificationService(config, pr_details)
        notifier.send_slack_notification(pr_url)

if __name__ == "__main__":
    main()
