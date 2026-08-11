import os
import sys
import logging
import subprocess
from typing import TYPE_CHECKING

from automation.domain.constants import SpecialTags
from automation.domain.models import TaskIntent, TaskCategory
from automation.interfaces.code_development_interface import ICodeDevelopmentService

if TYPE_CHECKING:
    from automation.dependency import Container

logger = logging.getLogger("automation.code_dev")

class CodeDevelopmentService(ICodeDevelopmentService):
    """Dedicated service handling the end-to-end Code Development Pipeline."""
    
    def __init__(self, container: "Container"):
        self.container = container
        self.config = container.config

    def _run_graphify(self, args: list) -> subprocess.CompletedProcess:
        """Helper executing graphify CLI via uv root project virtualenv or global binary."""
        cmd = ["uv", "run", "--project", ".."] + args
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, OSError):
            logger.warning("⚠️ 'uv' executable not found. Falling back to direct binary execution.")
            return subprocess.run(args, capture_output=True, text=True, timeout=30)

    def execute_pipeline(self) -> None:
        logger.info("🛠️ Executing Code Development Pipeline (Graphify AST + agy Engine + Git Branch & PR)...")

        # Step 1: Clean up workspace unwanted files
        cleanup_service = self.container.get_cleanup_service()
        cleanup_service.cleanup_unwanted_files()

        # Step 2: Build & Query Graphify AST Knowledge Graph
        logger.info("📊 Generating Graphify AST Knowledge Graph...")
        self._run_graphify(["graphify", "update", "."])
        
        graph_context = ""
        graph_res = self._run_graphify(["graphify", "query", self.config.user_prompt])
        if graph_res.returncode == 0 and graph_res.stdout.strip():
            graph_context = graph_res.stdout.strip()
            logger.info(f"🔍 Extracted Graphify AST Context ({len(graph_context)} chars).")

        # Step 3: Inject Rules into workspace
        rules_src = "../.agents/rules"
        rules_dst = ".agents/rules"
        if os.path.exists(rules_src):
            os.makedirs(rules_dst, exist_ok=True)
            subprocess.run(f"cp -r {rules_src}/* {rules_dst}/ 2>/dev/null || true", shell=True)

        # Step 4: Stream Execution of Native Google Antigravity CLI (agy) Engine
        full_prompt = f"{self.config.user_prompt}\n\n### Mandatory Graphify AST Knowledge Context:\n{graph_context}"
        logger.info(f"🤖 Executing Native Antigravity CLI (agy) with effort: {self.config.effort_val}...")
        
        cmd = [
            "agy", "--print", full_prompt,
            "--dangerously-skip-permissions",
            "--effort", self.config.effort_val
        ]
        
        with open(self.config.execution_log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
            proc.wait()

        if proc.returncode != 0:
            logger.error(f"❌ agy engine execution failed with exit code {proc.returncode}. Aborting PR pipeline.")
            return

        # Step 5: Check for SpecialTags.CLARIFICATION_NEEDED tag in agy output
        tag = SpecialTags.CLARIFICATION_NEEDED.value
        if os.path.exists(self.config.execution_log_path):
            with open(self.config.execution_log_path, "r", encoding="utf-8", errors="ignore") as f:
                log_content = f.read()
                if tag in log_content:
                    question = log_content.split(tag)[1].split("\n")[0].strip()
                    logger.info(f"❓ agy requested clarification: {question}")
                    clarification_intent = TaskIntent(
                        category=TaskCategory.CLARIFICATION_NEEDED,
                        confidence=1.0,
                        reasoning="Clarification requested by agy CLI engine.",
                        clarification_question=question
                    )
                    notifier = self.container.get_notification_service()
                    notifier.send_clarification_notification(clarification_intent)
                    return

        # Step 6: Clean up injected files before git staging
        cleanup_service.cleanup_unwanted_files()

        # Step 7: Resolve Gemini LLM Metadata Service & Git PR Service
        metadata_service = self.container.get_metadata_service()
        pr_details = metadata_service.generate_metadata()

        git_service = self.container.get_git_pr_service(pr_details)
        if not git_service.has_changes():
            logger.info("ℹ️ No file changes were produced by the agent.")
            return

        git_service.create_and_push_branch()
        pr_url = git_service.create_pull_request()

        # Step 8: Post Slack notification
        if pr_url:
            notifier = self.container.get_notification_service(pr_details)
            notifier.send_slack_notification(pr_url)
