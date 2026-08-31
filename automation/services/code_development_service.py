import os
import re
import shutil
import sys
import logging
import subprocess
from typing import Callable, Optional

from automation.domain.constants import SpecialTags, DEFAULT_AGY_MODEL
from automation.domain import TaskIntent, TaskCategory, WorkflowEnvironment, GitPRDetails
from automation.domain.telemetry import PipelineStage
from automation.interfaces import (
    ICodeDevelopmentService,
    IMetadataService,
    ISummarizerService,
    ISlackHistoryService,
    IGitPRService,
    INotificationService,
    IExecutionOutputClassifierService,
    ITelemetryService,
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
        telemetry_service: Optional[ITelemetryService] = None,
    ):
        self.config = config
        self.cleanup_service = cleanup_service
        self.slack_history_service = slack_history_service
        self.metadata_service = metadata_service
        self.summarizer_service = summarizer_service
        self.git_pr_service_factory = git_pr_service_factory
        self.notification_service_factory = notification_service_factory
        self.output_classifier = output_classifier
        self.telemetry_service = telemetry_service

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

    def _parse_activity_line(self, line: str) -> Optional[str]:
        """Extracts concise agent activity description from agy CLI stdout line."""
        raw = line.strip()
        if not raw:
            return None

        # 1. File edits / writes
        if any(kw in raw for kw in ("replace_file_content", "write_to_file", "Editing file", "Edited")):
            m = re.search(r"(?:\bTargetFile\b|\bTargetPath\b|\bfile\b|\bEditing file\b)[\s:=]+['\"]?([a-zA-Z0-9_./\-]+)", raw, re.IGNORECASE)
            if m:
                filename = os.path.basename(m.group(1))
                return f"Editing {filename}"
            return "Editing workspace files"

        # 2. File reads / views
        if any(kw in raw for kw in ("view_file", "Viewing file", "read_file")):
            m = re.search(r"(?:\bAbsolutePath\b|\bTargetFile\b|\bfile\b|\bViewing file\b)[\s:=]+['\"]?([a-zA-Z0-9_./\-]+)", raw, re.IGNORECASE)
            if m:
                filename = os.path.basename(m.group(1))
                return f"Reading {filename}"
            return "Reading workspace files"

        # 3. Searches
        if any(kw in raw for kw in ("grep_search", "find_by_name", "Searching")):
            m = re.search(r"(?:\bQuery\b|\bPattern\b|\bSearching\b)[\s:=]+['\"]?([^'\"\}]+)", raw, re.IGNORECASE)
            if m:
                query = m.group(1).strip()[:25]
                return f"Searching '{query}'"
            return "Searching codebase"

        # 4. Command execution
        if any(kw in raw for kw in ("run_command", "CommandLine", "Running command")):
            m = re.search(r"(?:\bCommandLine\b|\bcommand\b|\bRunning command\b)[\s:=]+['\"]?([^'\"\}]+)", raw, re.IGNORECASE)
            if m:
                cmd = m.group(1).strip()[:30]
                return f"Running `{cmd}`"
            return "Running build command"

        # 5. Planning / Thinking
        if "thinking" in raw.lower() or "planning" in raw.lower():
            return "Synthesizing code architecture"

        return None

    def execute_pipeline(self) -> None:
        logger.info("Executing Code Development Pipeline (Graphify AST + agy Engine + Git Branch & PR)...")

        # Step 0: Check for existing thread branch and initialize Slack telemetry card
        existing_branch = self.metadata_service.find_existing_thread_branch() or self.config.existing_branch
        is_update_run = bool(existing_branch)
        if self.telemetry_service:
            self.telemetry_service.initialize_card(is_update_run=is_update_run, existing_branch=existing_branch)

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
        if self.telemetry_service:
            self.telemetry_service.update_stage(PipelineStage.GRAPHIFY_AST, "Building AST knowledge graph...")

        logger.info("Generating Graphify AST Knowledge Graph...")
        self._run_graphify(["graphify", "update", "."])
        
        graph_context = ""
        graph_res = self._run_graphify(["graphify", "query", self.config.user_prompt])
        if graph_res.returncode == 0 and graph_res.stdout.strip():
            graph_context = graph_res.stdout.strip()
            logger.info(f"Extracted Graphify AST Context ({len(graph_context)} chars).")

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
        
        logger.info(f"Executing Native Antigravity CLI (agy) with model {agy_model}, --effort {effort_val}, --add-dir ., --print-timeout 15m0s...")
        
        if self.telemetry_service:
            self.telemetry_service.update_stage(PipelineStage.AGY_EXECUTION, f"Executing {agy_model}...")

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

                # Real-time stdout activity telemetry streaming
                if self.telemetry_service:
                    activity = self._parse_activity_line(line)
                    if activity:
                        self.telemetry_service.stream_activity(activity)

            proc.wait()

        if proc.returncode != 0:
            logger.error(f"agy engine execution failed with exit code {proc.returncode}. Aborting PR pipeline.")
            if self.telemetry_service:
                self.telemetry_service.fail(f"agy engine failed (exit code {proc.returncode})")
            return

        agy_full_output = "".join(agy_output_lines).strip()

        # Step 6: Evaluate agy CLI execution output intent semantically via injected classifier service
        if self.telemetry_service:
            self.telemetry_service.update_stage(PipelineStage.OUTPUT_VALIDATION, "Validating output intent...")

        if self.output_classifier:
            is_clarification, question = self.output_classifier.classify_output_intent(agy_full_output)
            if is_clarification and question:
                logger.info(f"agy requested clarification (LLM Verified): {question}")
                if self.telemetry_service:
                    self.telemetry_service.request_clarification(question)
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
        if self.telemetry_service:
            self.telemetry_service.update_stage(PipelineStage.GIT_PR_CREATION, "Synthesizing metadata and checking git changes...")

        pr_details = self.metadata_service.generate_metadata()

        git_service = self.git_pr_service_factory(pr_details)
        if not git_service.has_changes():
            logger.info("No file changes were produced by the agent.")
            # Use decoupled ISummarizerService to summarize verbose CLI output into a clean 1-sentence question
            concise_question = self.summarizer_service.summarize_clarification(agy_full_output)
            
            logger.info(f"Relaying concise clarification question to Slack thread: '{concise_question}'")
            if self.telemetry_service:
                self.telemetry_service.request_clarification(concise_question)
            clarification_intent = TaskIntent(
                category=TaskCategory.CLARIFICATION_NEEDED,
                confidence=1.0,
                reasoning="agy CLI output conversational response without code changes.",
                clarification_question=concise_question
            )
            notifier = self.notification_service_factory(None)
            notifier.send_clarification_notification(clarification_intent)
            return

        if self.telemetry_service:
            self.telemetry_service.update_stage(PipelineStage.GIT_PR_CREATION, f"Pushing branch '{pr_details.branch_name}'...")

        git_service.create_and_push_branch()
        pr_url = git_service.create_pull_request()

        # Step 9: Post PR notification and finalize telemetry
        if pr_url:
            if self.telemetry_service:
                self.telemetry_service.complete(pr_url=pr_url, branch_name=pr_details.branch_name)
            notifier = self.notification_service_factory(pr_details)
            notifier.send_pr_notification(pr_url)
        else:
            if self.telemetry_service:
                self.telemetry_service.fail("Failed to create Pull Request on GitHub")
