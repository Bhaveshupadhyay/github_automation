"""Service for cross-repository dependency and branch resolution."""
import logging
import re
import subprocess
from typing import Any, Dict, Optional, Tuple

from automation.domain.branch_resolver import BranchResolutionResult, ResolutionSource
from automation.interfaces.branch_resolver_interface import IBranchResolver

logger = logging.getLogger(__name__)

# Git ref naming standards (enforces security against option injection and shell metacharacters)
# - No leading dashes (-) to prevent CLI option injection (--upload-pack, etc.)
# - Allowed chars: alphanumeric, _, -, ., /
# - No consecutive slashes (//)
# - No parent directory traversal (..)
# - Cannot start or end with slash (/)
# - Cannot end with .lock
BRANCH_REGEX = re.compile(
    r"^(?!/)(?!.*//)(?!.*\.\.)[a-zA-Z0-9_\-\./]+(?<!/)(?<!\.lock)$"
)

# Explicit declaration regexes for PR descriptions
# Supports Markdown headers, bold, links, code tags, and comments
# Matches: "Backend Branch: feat/x", "Target Branch: feat/x", "**Backend Branch:** feat/x", etc.
EXPLICIT_BRANCH_REGEX = re.compile(
    r"(?i)(?:backend|target)[\s_\-*]*branch[\s_\-*]*[:=][\s_\-*]*[*_`'\"\[]*([a-zA-Z0-9_\-\./]+)[*_`'\"\]]*"
)
# Matches: "Backend PR: #123", "Target PR: 123", "**Backend PR:** #123", etc.
EXPLICIT_PR_REGEX = re.compile(
    r"(?i)(?:backend|target)[\s_\-*]*pr[\s_\-*]*[:=][\s_\-*]*[*_`'\"\[]*#?([0-9]+)[*_`'\"\]]*"
)


class BranchResolverService(IBranchResolver):
    """Resolves which backend branch to pair with an incoming frontend/mobile PR."""

    def __init__(self, command_timeout_seconds: float = 5.0) -> None:
        self._command_timeout = command_timeout_seconds

    @staticmethod
    def sanitize_branch_name(branch_name: str) -> str:
        """Sanitizes and validates a git branch name against injection attacks.

        Args:
            branch_name: The branch name string to validate.

        Returns:
            The sanitized branch name string.

        Raises:
            ValueError: If the branch name is empty, starts with a dash, or contains invalid characters.
        """
        if not branch_name or not isinstance(branch_name, str):
            raise ValueError("Branch name must be a non-empty string.")

        trimmed = branch_name.strip()
        if trimmed.startswith("-"):
            raise ValueError(f"Security error: Branch name cannot start with a dash ('{trimmed}').")

        if not BRANCH_REGEX.match(trimmed):
            raise ValueError(
                f"Security error: Branch name contains invalid ref characters or sequences ('{trimmed}')."
            )

        return trimmed

    @staticmethod
    def sanitize_repo_url(repo_url: str) -> str:
        """Sanitizes and validates a git repository URL or local path.

        Args:
            repo_url: The repository URL or path.

        Returns:
            The sanitized repository URL.

        Raises:
            ValueError: If the repository URL is empty or starts with a dash.
        """
        if not repo_url or not isinstance(repo_url, str):
            raise ValueError("Repository URL must be a non-empty string.")

        trimmed = repo_url.strip()
        if trimmed.startswith("-"):
            raise ValueError(f"Security error: Repository URL cannot start with a dash ('{trimmed}').")

        return trimmed

    def check_remote_branch_exists(self, backend_repo_url: str, branch_name: str) -> bool:
        """Probes the remote backend repository using 'git ls-remote'."""
        try:
            sanitized_url = self.sanitize_repo_url(backend_repo_url)
            sanitized_branch = self.sanitize_branch_name(branch_name)
        except ValueError as e:
            logger.warning(f"Sanitization rejected remote branch check: {e}")
            return False

        cmd = [
            "git",
            "ls-remote",
            "--heads",
            sanitized_url,
            f"refs/heads/{sanitized_branch}",
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._command_timeout,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                # Output format: "<SHA>\trefs/heads/<branch>"
                return f"refs/heads/{sanitized_branch}" in result.stdout
            return False
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
            logger.warning(
                f"git ls-remote probe failed for '{sanitized_branch}' on '{sanitized_url}': {exc}"
            )
            return False

    def _extract_explicit_linkage(self, pr_body: Optional[str]) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Parses PR body text for explicit backend branch or PR linkage declarations."""
        if not pr_body or not isinstance(pr_body, str):
            return None

        # 1. Check for explicit branch declaration first
        branch_match = EXPLICIT_BRANCH_REGEX.search(pr_body)
        if branch_match:
            candidate_branch = branch_match.group(1).rstrip(".,;")
            try:
                sanitized = self.sanitize_branch_name(candidate_branch)
                return sanitized, {"matched_pattern": "branch", "raw_declaration": branch_match.group(0)}
            except ValueError as e:
                logger.warning(f"Ignored invalid explicit branch '{candidate_branch}' in PR body: {e}")

        # 2. Check for explicit PR number declaration
        pr_match = EXPLICIT_PR_REGEX.search(pr_body)
        if pr_match:
            pr_num = pr_match.group(1)
            target_ref = f"refs/pull/{pr_num}/head"
            return target_ref, {"matched_pattern": "pr_number", "pr_number": int(pr_num)}

        return None

    def resolve_branch(
        self,
        pr_body: Optional[str],
        source_branch: str,
        backend_repo_url: str,
        default_branch: str = "dev",
        new_backend_routes_detected: bool = False,
    ) -> BranchResolutionResult:
        """Determines which backend repository branch must be paired with an incoming PR.

        Enforces the three-tier resolution strategy:
        - Tier 1: Explicit metadata in PR body (e.g. 'Backend Branch: <branch>' or 'Backend PR: #<num>')
        - Tier 2: Remote branch matching (identical branch name in backend repository)
        - Tier 3: Default fallback ('dev', or 'main' if 'dev' is unavailable)
        """
        sanitized_url = self.sanitize_repo_url(backend_repo_url)
        sanitized_source = self.sanitize_branch_name(source_branch)

        # Tier 1: Explicit Metadata Declaration
        explicit_linkage = self._extract_explicit_linkage(pr_body)
        if explicit_linkage:
            target_ref, details = explicit_linkage
            logger.info(f"Resolved branch via Tier 1 (Explicit PR Body): '{target_ref}'")
            return BranchResolutionResult(
                target_branch=target_ref,
                target_repo_url=sanitized_url,
                source_branch=sanitized_source,
                resolution_source=ResolutionSource.EXPLICIT_PR_BODY,
                clarification_needed=False,
                details=details,
            )

        # Tier 2: Remote Branch Name Matching
        if self.check_remote_branch_exists(sanitized_url, sanitized_source):
            logger.info(f"Resolved branch via Tier 2 (Remote Branch Match): '{sanitized_source}'")
            return BranchResolutionResult(
                target_branch=sanitized_source,
                target_repo_url=sanitized_url,
                source_branch=sanitized_source,
                resolution_source=ResolutionSource.REMOTE_BRANCH_MATCH,
                clarification_needed=False,
                details={"matched_remote_head": f"refs/heads/{sanitized_source}"},
            )

        # Tier 3: Default Fallback
        # Check if requested default_branch exists on remote; if not, check 'main'
        fallback_target = default_branch
        try:
            sanitized_default = self.sanitize_branch_name(default_branch)
            if self.check_remote_branch_exists(sanitized_url, sanitized_default):
                fallback_target = sanitized_default
            elif sanitized_default != "main" and self.check_remote_branch_exists(sanitized_url, "main"):
                fallback_target = "main"
        except ValueError:
            fallback_target = "dev"

        clarification_needed = False
        clarification_message = None

        if new_backend_routes_detected:
            clarification_needed = True
            clarification_message = (
                f"⚠️ **Cross-Repository Dependency Notice**:\n"
                f"This pull request introduces calls to unmerged backend endpoints, but no matching backend branch "
                f"was found. The automated QA pipeline defaulted to testing against backend branch `{fallback_target}`.\n\n"
                f"If your frontend changes require unmerged backend updates, please specify the backend branch or PR "
                f"in your pull request description:\n"
                f"```markdown\n"
                f"Backend Branch: <branch_name>\n"
                f"```\n"
                f"or\n"
                f"```markdown\n"
                f"Backend PR: #<pr_number>\n"
                f"```"
            )

        logger.info(f"Resolved branch via Tier 3 (Default Fallback): '{fallback_target}'")
        return BranchResolutionResult(
            target_branch=fallback_target,
            target_repo_url=sanitized_url,
            source_branch=sanitized_source,
            resolution_source=ResolutionSource.DEFAULT_FALLBACK,
            clarification_needed=clarification_needed,
            clarification_message=clarification_message,
            details={"fallback_branch": fallback_target, "routes_flagged": new_backend_routes_detected},
        )
