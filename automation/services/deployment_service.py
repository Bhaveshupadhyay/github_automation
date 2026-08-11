import os
import logging
import subprocess
from typing import Dict, Any
from automation.domain.models import WorkflowEnvironment, TaskIntent

logger = logging.getLogger("automation.deployment")

class DeploymentService:
    """Service responsible for executing operational deployment tasks (Fastlane, Wrangler, GitHub Workflows)."""
    
    def __init__(self, config: WorkflowEnvironment):
        self.config = config

    def execute_deployment(self, intent: TaskIntent) -> Dict[str, Any]:
        action = intent.target_action or "deploy_general"
        logger.info(f"🚀 Executing Operational Deployment Action: '{action}' for prompt: '{self.config.user_prompt}'")
        
        output_logs = []
        status_success = True

        # Action 1: Deploy Cloudflare Worker
        if "cloudflare" in action.lower() or "worker" in action.lower():
            logger.info("⚡ Executing Cloudflare Wrangler Deployment...")
            cmd = ["npx", "wrangler", "deploy"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
                output_logs.append(res.stdout or res.stderr)
                status_success = (res.returncode == 0)
            except subprocess.TimeoutExpired:
                output_logs.append("❌ Cloudflare Wrangler deployment timed out after 120s.")
                status_success = False

        # Action 2: Deploy to App Store / Play Store via Fastlane
        elif "app_store" in action.lower() or "play_store" in action.lower() or "fastlane" in action.lower():
            logger.info("📱 Executing Fastlane Mobile Deployment...")
            cmd = ["bundle", "exec", "fastlane", "release"]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=300)
                output_logs.append(res.stdout or res.stderr)
                status_success = (res.returncode == 0)
            except subprocess.TimeoutExpired:
                output_logs.append("❌ Fastlane mobile deployment timed out after 300s.")
                status_success = False

        # Action 3: Trigger GitHub Release / Deploy Workflow
        elif "workflow" in action.lower() or "github" in action.lower():
            logger.info("Triggering GitHub Release Workflow...")
            cmd = ["gh", "workflow", "run", "deploy.yml", "--repo", self.config.target_repo]
            try:
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
                output_logs.append(res.stdout or res.stderr)
                status_success = (res.returncode == 0)
            except subprocess.TimeoutExpired:
                output_logs.append("❌ GitHub Workflow dispatch timed out after 30s.")
                status_success = False

        # Action 4: Custom Deploy Script fallback or fail-closed on unsupported action
        else:
            if os.path.exists("./deploy.sh"):
                logger.info("📜 Executing custom ./deploy.sh script...")
                try:
                    res = subprocess.run(["bash", "./deploy.sh"], capture_output=True, text=True, timeout=180)
                    output_logs.append(res.stdout or res.stderr)
                    status_success = (res.returncode == 0)
                except subprocess.TimeoutExpired:
                    output_logs.append("❌ Custom ./deploy.sh timed out after 180s.")
                    status_success = False
            else:
                logger.warning(f"⚠️ Unsupported deployment action '{action}' and no ./deploy.sh found.")
                output_logs.append(f"Unsupported deployment action: '{action}'. No ./deploy.sh script found.")
                status_success = False

        return {
            "action": action,
            "success": status_success,
            "output": "\n".join(output_logs)[:1000],
            "reasoning": intent.reasoning
        }
