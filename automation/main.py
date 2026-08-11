import os
import sys
import logging
import subprocess
from automation.dependency import container
from automation.domain.models import TaskCategory

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)
logger = logging.getLogger("automation.main")

def run_code_development_pipeline(config):
    """Executes full Code Development Pipeline: Graphify AST -> agy Engine -> Gemini PR Manager -> Git Push & PR."""
    logger.info("🛠️ Starting Code Development Engine...")

    # Step 1: Clean up workspace unwanted files
    cleanup_service = container.get_cleanup_service()
    cleanup_service.cleanup_unwanted_files()

    # Step 2: Build & Query Graphify AST Knowledge Graph
    logger.info("📊 Generating Graphify AST Knowledge Graph...")
    subprocess.run(["graphify", "update", "."], capture_output=True, text=True)
    
    graph_context = ""
    graph_res = subprocess.run(["graphify", "query", config.user_prompt], capture_output=True, text=True)
    if graph_res.returncode == 0 and graph_res.stdout.strip():
        graph_context = graph_res.stdout.strip()
        logger.info(f"🔍 Extracted Graphify AST Context ({len(graph_context)} chars).")

    # Step 3: Inject Rules into workspace
    rules_src = "../.agents/rules"
    rules_dst = ".agents/rules"
    if os.path.exists(rules_src):
        os.makedirs(rules_dst, exist_ok=True)
        subprocess.run(f"cp -r {rules_src}/* {rules_dst}/ 2>/dev/null || true", shell=True)

    # Step 4: Execute Native Google Antigravity CLI (agy) Engine
    full_prompt = f"{config.user_prompt}\n\n### Mandatory Graphify AST Knowledge Context:\n{graph_context}"
    logger.info(f"🤖 Executing Native Antigravity CLI (agy) with effort: {config.effort_val}...")
    
    cmd = [
        "agy", "--print", full_prompt,
        "--dangerously-skip-permissions",
        "--effort", config.effort_val
    ]
    
    with open(config.execution_log_path, "w", encoding="utf-8") as log_file:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in proc.stdout:
            sys.stdout.write(line)
            sys.stdout.flush()
            log_file.write(line)
        proc.wait()

    # Step 5: Check for Clarification Request in agy output
    if os.path.exists(config.execution_log_path):
        with open(config.execution_log_path, "r", encoding="utf-8", errors="ignore") as f:
            log_content = f.read()
            if "CLARIFICATION_NEEDED:" in log_content:
                question = log_content.split("CLARIFICATION_NEEDED:")[1].split("\n")[0].strip()
                logger.info(f"❓ agy requested clarification: {question}")
                notifier = container.get_notification_service()
                notifier.send_clarification_notification(question)
                return

    # Step 6: Clean up injected files before git staging
    cleanup_service.cleanup_unwanted_files()

    # Step 7: Resolve Gemini LLM Metadata Service & Git PR Service
    metadata_service = container.get_metadata_service()
    pr_details = metadata_service.generate_metadata()

    git_service = container.get_git_pr_service(pr_details)
    if not git_service.has_changes():
        logger.info("ℹ️ No file changes were produced by the agent.")
        return

    git_service.create_and_push_branch()
    pr_url = git_service.create_pull_request()

    # Step 8: Post Slack notification
    if pr_url:
        notifier = container.get_notification_service(pr_details)
        notifier.send_slack_notification(pr_url)

def main():
    try:
        config = container.config
    except Exception as e:
        logger.error(f"❌ Invalid Environment Configuration: {e}")
        sys.exit(1)

    logger.info(f"📌 Received Prompt for Repo '{config.target_repo}': {config.user_prompt}")

    # 1. Classify Task Intent via LLM Router Service
    router = container.get_intent_router_service()
    intent = router.classify_intent()

    # Route A: Clarification Needed
    if intent.category == TaskCategory.CLARIFICATION_NEEDED:
        logger.info(f"❓ Task requires user clarification: {intent.clarification_question}")
        notifier = container.get_notification_service()
        notifier.send_clarification_notification(intent)
        return

    # Route B: Operational Deployment Task (Fastlane, Wrangler, Workflow)
    elif intent.category == TaskCategory.DEPLOYMENT_DEVOPS:
        logger.info(f"🚀 Routing to Operational Deployment Engine (Action: '{intent.target_action}')")
        deployer = container.get_deployment_service()
        deploy_result = deployer.execute_deployment(intent)
        notifier = container.get_notification_service()
        notifier.send_deployment_notification(deploy_result)
        return

    # Route C: Code Development Task (Graphify AST + agy Engine + Git Branch & PR)
    elif intent.category == TaskCategory.CODE_DEVELOPMENT:
        run_code_development_pipeline(config)

if __name__ == "__main__":
    main()
