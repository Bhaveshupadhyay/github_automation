from abc import ABC, abstractmethod
from src.domain.entities import CodeModification, PullRequestResult

class ILLMGateway(ABC):
    """Abstract interface for LLM code generation gateway."""
    
    @abstractmethod
    def generate_code_changes(self, user_prompt: str, context: str) -> CodeModification:
        pass

class IGitGateway(ABC):
    """Abstract interface for Git operations & Pull Request management."""

    @abstractmethod
    def prepare_workspace(self, repository: str) -> None:
        """Clones or prepares the target repository workspace."""
        pass

    @abstractmethod
    def apply_and_push_changes(self, modification: CodeModification, repository: str = "") -> str:
        """Applies files to disk and pushes feature branch. Returns branch name."""
        pass

    @abstractmethod
    def create_and_merge_pr(self, branch_name: str, commit_message: str, user_prompt: str, repository: str = "", auto_merge: bool = False) -> PullRequestResult:
        """Creates pull request via GitHub API and optionally auto-merges it."""
        pass

class IIndexerGateway(ABC):
    """Abstract interface for Graphify AST codebase indexing."""

    @abstractmethod
    def get_scoped_context(self, user_prompt: str) -> str:
        pass

class INotifierGateway(ABC):
    """Abstract interface for Telegram/Slack notification delivery."""

    @abstractmethod
    def notify(self, message: str) -> None:
        pass
