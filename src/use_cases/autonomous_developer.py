from src.domain.interfaces import ILLMGateway, IGitGateway, IIndexerGateway, INotifierGateway
from src.domain.entities import CodeChangeRequest
from src.core.config import settings
from src.core.logger import logger

class AutonomousDeveloperUseCase:
    """
    Use Case orchestrating the end-to-end autonomous development workflow:
    1. Prepare & clone target repository workspace
    2. Query Graphify context inside target repository
    3. Generate code changes via LLM Function Calling
    4. Push git branch & create PR on target repository (auto-merge optional)
    5. Notify Slack/Telegram channels
    """

    def __init__(
        self,
        llm_gateway: ILLMGateway,
        git_gateway: IGitGateway,
        indexer_gateway: IIndexerGateway,
        notifier_gateway: INotifierGateway
    ):
        self.llm_gateway = llm_gateway
        self.git_gateway = git_gateway
        self.indexer_gateway = indexer_gateway
        self.notifier_gateway = notifier_gateway

    def execute(self, request: CodeChangeRequest) -> None:
        target_repo = request.repository or "default repository"
        logger.info(f"Target repository for execution: {target_repo}")

        self.notifier_gateway.notify(
            f"⚡ *AI Agent Active*\n\n"
            f"📦 *Repository:* `{target_repo}`\n"
            f"📌 *Prompt:* `{request.user_prompt}`\n\n"
            f"🧠 Querying Graphify AST index & analyzing code..."
        )

        # 1. Prepare target repository workspace
        self.git_gateway.prepare_workspace(request.repository)

        # 2. Fetch scoped context from Graphify inside target repository workspace
        context = self.indexer_gateway.get_scoped_context(request.user_prompt)

        # 3. Call LLM Gateway to generate code changes
        modification = self.llm_gateway.generate_code_changes(request.user_prompt, context)

        if not modification.files:
            self.notifier_gateway.notify("⚠️ *AI Response*: No files were updated.")
            return

        # 4. Apply changes and push git branch to target repository
        branch_name = self.git_gateway.apply_and_push_changes(modification, repository=request.repository)

        # 5. Create PR on target repository (Auto-merge disabled by default!)
        pr_result = self.git_gateway.create_and_merge_pr(
            branch_name=branch_name,
            commit_message=modification.commit_message,
            user_prompt=request.user_prompt,
            repository=request.repository,
            auto_merge=settings.auto_merge_pr
        )

        # 6. Notify status with PR link for review!
        if pr_result.is_merged:
            self.notifier_gateway.notify(
                f"✅ *Task Complete & Auto-Merged!*\n\n"
                f"📦 *Repository:* `{target_repo}`\n"
                f"📌 *Prompt:* `{request.user_prompt}`\n"
                f"🔗 *PR Link:* <{pr_result.pr_url}|PR #{pr_result.pr_number}>\n"
                f"🚀 *Deploying automatically!*"
            )
        else:
            self.notifier_gateway.notify(
                f"🚀 *Pull Request Created & Ready for Review!*\n\n"
                f"📦 *Repository:* `{target_repo}`\n"
                f"📌 *Prompt:* `{request.user_prompt}`\n"
                f"🌿 *Branch:* `{pr_result.branch_name}`\n"
                f"🔗 *PR Link:* <{pr_result.pr_url}|PR #{pr_result.pr_number}>\n\n"
                f"👀 *Please review and merge when ready!*"
            )
