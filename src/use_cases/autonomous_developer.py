from src.domain.interfaces import ILLMGateway, IGitGateway, IIndexerGateway, INotifierGateway
from src.domain.entities import CodeChangeRequest

class AutonomousDeveloperUseCase:
    """
    Use Case orchestrating the end-to-end autonomous development workflow:
    1. Query Graphify context
    2. Generate code changes via LLM Function Calling
    3. Push git branch & create/auto-merge PR
    4. Notify Slack/Telegram channels
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
        self.notifier_gateway.notify(
            f"⚡ *AI Agent Active*\n\n*Prompt:* `{request.user_prompt}`\n\n🧠 Querying Graphify AST index & analyzing code..."
        )

        # 1. Fetch scoped context from Graphify
        context = self.indexer_gateway.get_scoped_context(request.user_prompt)

        # 2. Call LLM Gateway
        modification = self.llm_gateway.generate_code_changes(request.user_prompt, context)

        if not modification.files:
            self.notifier_gateway.notify("⚠️ *AI Response*: No files were updated.")
            return

        # 3. Apply changes and push git branch
        branch_name = self.git_gateway.apply_and_push_changes(modification)

        # 4. Create and Auto-Merge PR
        pr_result = self.git_gateway.create_and_merge_pr(
            branch_name=branch_name,
            commit_message=modification.commit_message,
            user_prompt=request.user_prompt
        )

        # 5. Notify status
        self.notifier_gateway.notify(
            f"✅ *Task Complete & Auto-Merged!*\n\n"
            f"📌 *Prompt:* `{request.user_prompt}`\n"
            f"🔗 *PR Link:* <{pr_result.pr_url}|PR #{pr_result.pr_number}>\n"
            f"🚀 *Deploying automatically!*"
        )
