import os
import shutil
import sys
import logging
import subprocess
from typing import Callable, Optional

from automation.domain.constants import SpecialTags, DEFAULT_AGY_MODEL
from automation.domain import TaskIntent, TaskCategory, WorkflowEnvironment, GitPRDetails
from automation.interfaces import (
    ICodeDevelopmentService,
    IMetadataService,
    ISummarizerService,
    ISlackHistoryService,
    IGitPRService,
    INotificationService,
    IExecutionOutputClassifierService,
)
from automation.services.cleanup_service import WorkspaceCleanupService

logger = logging.getLogger("automation.code_dev")

class CodeDevelopmentService(ICodeDevelopmentService):
    """Dedicated service handling the end-to-end Code Development Pipeline using Constructor DI."""
    
    def __init__(self,
        config: WorkflowEnvironment,
        cleanup_service: WorkspaceCleanupService,
        slack_history_service: ISlackHistoryService,
        metadata_service: IMetadataService,
        summarizer_service: ISummarizerService,
        git_pr_service_factory: Callable[[GitPRDetails], IGitPRService],
        notification_service_factory: Callable[[Optional[GitPRDetails]], INotificationService],
        output_classifier: Optional[IExecutionOutputClassifierService] = None,
    ):
        self.config = config
        self.cleanup_service = cleanup_service
        self.slack_history_service = slack_history_service
        self.metadata_service = metadata_service
        self.summarizer_service = summarizer_service
        self.git_pr_service_factory = git_pr_service_factory
        self.notification_service_factory = notification_service_factory
        self.output_classifier = output_classifier

    def _run_graphify(self, args: list) -> subprocess.CompletedProcess:
        """Helper executing graphify CLI via uv root project virtualenv or global binary."""
        cmd = ["uv", "run", "--project", ".."] + args
        try:
            return subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        except (FileNotFoundError, OSError):
            logger.warning("⚠️ 'uv' executable not found. Falling back to direct binary execution.")
            return subprocess.run(args, capture_output=True, text=True, timeout=30)

    def _resolve_agy_binary(self) -> str:
        """Finds the absolute path to the agy CLI binary across system PATH and standard install directories."""
        path_which = shutil.which("agy")
        if path_which and os.path.exists(path_which):
            return path_which

        home = os.path.expanduser("~")
        candidate_paths = [
            os.path.join(home, ".local", "bin", "agy"),
            os.path.join(home, ".gemini", "antigravity-cli", "bin", "agy"),
            os.path.join(home, ".gemini", "antigravity-cli", "agy"),
            "/usr/local/bin/agy",
            "/usr/bin/agy",
        ]
        for p in candidate_paths:
            if os.path.exists(p) and os.access(p, os.X_OK):
                logger.info(f"📍 Resolved agy binary at explicit path: {p}")
                return p

        return "agy"

    def execute_pipeline(self) -> None:
        logger.info("🛠️ Executing Code Development Pipeline (Graphify AST + agy Engine + Git Branch & PR)...")

        # Step 1: Clean up workspace unwanted files
        self.cleanup_service.cleanup_unwanted_files()

        # Step 2: Retrieve Full Slack Thread Conversation History if available
        thread_history = ""
        try:
            fetched_history = self.slack_history_service.fetch_thread_history()
            if fetched_history:
                thread_history = f"\n\n### Full Slack Conversation Thread History:\n{fetched_history}"
        except Exception as e:
            logger.debug(f"Slack history lookup skipped: {e}")

        # Step 3: Build & Query Graphify AST Knowledge Graph
        logger.info("📊 Generating Graphify AST Knowledge Graph...")
        self._run_graphify(["graphify", "update", "."])
        
        graph_context = ""
        graph_res = self._run_graphify(["graphify", "query", self.config.user_prompt])
        if graph_res.returncode == 0 and graph_res.stdout.strip():
            graph_context = graph_res.stdout.strip()
            logger.info(f"🔍 Extracted Graphify AST Context ({len(graph_context)} chars).")

        # Step 4: Non-destructively inject framework rules and skills into workspace
        for agent_sub in ["rules", "skills"]:
            src_dir = f"../.agents/{agent_sub}"
            dst_dir = f".agents/{agent_sub}"
            if os.path.exists(src_dir):
                try:
                    shutil.copytree(src_dir, dst_dir, dirs_exist_ok=True)
                except Exception as e:
                    logger.debug(f"Copying {agent_sub} skipped: {e}")

        # Step 5: Stream Execution of Native Google Antigravity CLI (agy) Engine in Current Directory '.'
        workspace_rule = "\n\nCRITICAL WORKSPACE RULE: You MUST modify and edit existing files ONLY inside the current working directory ('.'). Never create new subfolders in ~/.gemini/antigravity-cli/scratch or any external directory."
        full_prompt = f"{self.config.user_prompt}{thread_history}{workspace_rule}\n\n### Mandatory Graphify AST Knowledge Context:\n{graph_context}"
        agy_model = DEFAULT_AGY_MODEL
        effort_val = self.config.effort_val if self.config.effort_val else "high"
        
        logger.info(f"🤖 Executing Native Antigravity CLI (agy) with model {agy_model}, --effort {effort_val}, --add-dir ., --print-timeout 15m0s...")
        
        agy_bin = self._resolve_agy_binary()
        cmd = [
            agy_bin, "--print", full_prompt,
            "--dangerously-skip-permissions",
            "--add-dir", ".",
            "--model", agy_model,
            "--effort", effort_val,
            "--print-timeout", "15m0s"
        ]
        
        agy_output_lines = []
        with open(self.config.execution_log_path, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
            for line in proc.stdout:
                sys.stdout.write(line)
                sys.stdout.flush()
                log_file.write(line)
                if len(agy_output_lines) < 200:
                    agy_output_lines.append(line)
            proc.wait()

        if proc.returncode != 0:
            logger.error(f"❌ agy engine execution failed with exit code {proc.returncode}. Aborting PR pipeline.")
            return

        agy_full_output = "".join(agy_output_lines).strip()

        # Step 6: Evaluate agy CLI execution output intent semantically via injected classifier service
        if self.output_classifier:
            is_clarification, question = self.output_classifier.classify_output_intent(agy_full_output)
            if is_clarification and question:
                logger.info(f"❓ agy requested clarification (LLM Verified): {question}")
                clarification_intent = TaskIntent(
                    category=TaskCategory.CLARIFICATION_NEEDED,
                    confidence=1.0,
                    reasoning="Clarification requested by agy CLI engine.",
                    clarification_question=question
                )
                notifier = self.notification_service_factory(None)
                notifier.send_clarification_notification(clarification_intent)
                return

        # Step 7: Clean up injected files before git staging
        self.cleanup_service.cleanup_unwanted_files()

        # Step 8: Resolve Gemini LLM Metadata Service & Git PR Service
        pr_details = self.metadata_service.generate_metadata()

        git_service = self.git_pr_service_factory(pr_details)
        if not git_service.has_changes():
            logger.info("ℹ️ No file changes were produced by the agent.")
            # Use decoupled ISummarizerService to summarize verbose CLI output into a clean 1-sentence question
            concise_question = self.summarizer_service.summarize_clarification(agy_full_output)
            
            logger.info(f"💬 Relaying concise clarification question to Slack thread: '{concise_question}'")
            clarification_intent = TaskIntent(
                category=TaskCategory.CLARIFICATION_NEEDED,
                confidence=1.0,
                reasoning="agy CLI output conversational response without code changes.",
                clarification_question=concise_question
            )
            notifier = self.notification_service_factory(None)
            notifier.send_clarification_notification(clarification_intent)
            return

        git_service.create_and_push_branch()
        pr_url = git_service.create_pull_request()

        # Step 9: Post PR notification
        if pr_url:
            notifier = self.notification_service_factory(pr_details)
            notifier.send_pr_notification(pr_url)
