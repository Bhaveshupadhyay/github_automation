"""Service for cross-repository dependency and branch resolution."""
import json
import logging
import os
import re
import subprocess
import urllib.request
from typing import Any, Dict, Optional, Tuple

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None
    types = None

from automation.core import get_gemini_api_key, normalize_gemini_model
from automation.domain.branch_resolver import (
    AIExtractedBranch,
    BranchResolutionResult,
    ResolutionSource,
)
from automation.interfaces.branch_resolver_interface import IBranchResolver

logger = logging.getLogger(__name__)

# Git ref naming standards (enforces security against option injection and shell metacharacters)
BRANCH_REGEX = re.compile(
    r"^(?!/)(?!.*//)(?!.*\.\.)[a-zA-Z0-9_\-\./]+(?<!/)(?<!\.lock)$"
)

# Explicit declaration regexes for PR descriptions
EXPLICIT_BRANCH_REGEX = re.compile(
    r"(?i)(?:backend|target)[\s_\-*]*branch[\s_\-*]*[:=][\s_\-*]*[*_`'\"\[]*([a-zA-Z0-9_\-\./]+)[*_`'\"\]]*"
)
EXPLICIT_PR_REGEX = re.compile(
    r"(?i)(?:backend|target)[\s_\-*]*pr[\s_\-*]*[:=][\s_\-*]*[*_`'\"\[]*#?([0-9]+)[*_`'\"\]]*"
)

# Semantic cues indicating negation, obsolescence, or ambiguity
NEGATION_MARKERS = [
    "do not use",
    "don't use",
    "not using",
    "ignore",
    "discard",
    "deprecated",
    "superseded",
    "obsolete",
    "no longer",
    "instead of",
    "rather than",
    "~~",  # markdown strike-through
]

CONVERSATIONAL_CUES = [
    "backend",
    "api",
    "server",
    "branch",
    "pr #",
    "pull request",
    "service",
    "unmerged",
    "depends on",
    "dependency",
    "pairing",
]


class BranchResolverService(IBranchResolver):
    """Resolves which backend branch to pair with an incoming frontend/mobile PR."""

    def __init__(
        self,
        command_timeout_seconds: float = 5.0,
        api_key: Optional[str] = None,
        gemini_model: Optional[str] = None,
        genai_client: Optional[Any] = None,
    ) -> None:
        self._command_timeout = command_timeout_seconds
        self._api_key = api_key if api_key is not None else get_gemini_api_key()
        self._model_name = normalize_gemini_model(gemini_model)
        self._genai_client = genai_client

    @staticmethod
    def sanitize_branch_name(branch_name: str) -> str:
        """Sanitizes and validates a git branch name against injection attacks."""
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
        """Sanitizes and validates a git repository URL or local path."""
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
                return f"refs/heads/{sanitized_branch}" in result.stdout
            return False
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
            logger.warning(
                f"git ls-remote probe failed for '{sanitized_branch}' on '{sanitized_url}': {exc}"
            )
            return False

    def _is_ambiguous_or_negated(self, pr_body: str, candidate_ref: str) -> bool:
        """Detects if a candidate branch in PR body is negated, crossed-out, or ambiguous."""
        body_lower = pr_body.lower()

        # Check for multiple branch declarations
        matches = EXPLICIT_BRANCH_REGEX.findall(pr_body)
        if len(matches) > 1:
            return True

        # Check for strike-through markdown
        if f"~~{candidate_ref}~~" in pr_body or f"~~`{candidate_ref}`~~" in pr_body:
            return True

        # Search for negation phrases within close proximity of the candidate
        candidate_pos = body_lower.find(candidate_ref.lower())
        if candidate_pos != -1:
            window_start = max(0, candidate_pos - 120)
            window_end = min(len(body_lower), candidate_pos + len(candidate_ref) + 120)
            surrounding_context = body_lower[window_start:window_end]
            for marker in NEGATION_MARKERS:
                if marker in surrounding_context:
                    return True

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

    def extract_branch_with_ai(
        self,
        pr_body: str,
        backend_repo_url: str,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Uses Gemini semantic analysis to extract and verify backend branch dependencies.

        Returns:
            Tuple of (resolved_ref, details_dict) or None if inconclusive.
        """
        if not self._api_key or not pr_body.strip():
            logger.info("Skipping AI semantic extraction (no API key or empty PR body).")
            return None

        system_instruction = (
            "You are an expert Git dependency resolution engine. Analyze the provided Pull Request "
            "description and determine if the author intends to link or test against a specific backend "
            "repository branch or pull request.\n"
            "Distinguish between branches the author recommends vs branches they reject, deprecate, or mention as obsolete.\n"
            "Extract:\n"
            "- target_branch: the exact backend branch name (or null if not specified or PR number is used)\n"
            "- target_pr_number: the backend pull request number (or null if not specified)\n"
            "- confidence: a float from 0.0 to 1.0\n"
            "- reasoning: brief explanation\n"
            "- is_negated_or_deprecated: true if the author mentions a branch but explicitly says NOT to use it\n"
            "If no backend branch or PR is intended or if the text is irrelevant, return nulls with 0.0 confidence."
        )

        prompt_content = f"PR Description:\n```markdown\n{pr_body[:4000]}\n```"

        ai_extracted: Optional[AIExtractedBranch] = None

        # 1. Try via google.genai Client (or injected mock client)
        if self._genai_client is not None:
            try:
                response = self._genai_client.models.generate_content(
                    model=self._model_name,
                    contents=prompt_content,
                    config={"response_mime_type": "application/json"},
                )
                raw_text = response.text if hasattr(response, "text") else str(response)
                parsed = json.loads(raw_text)
                ai_extracted = AIExtractedBranch(**parsed)
            except Exception as e:
                logger.warning(f"Injected genai_client call failed: {e}")
        elif genai is not None:
            try:
                client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(
                        headers={"X-goog-api-key": self._api_key},
                        timeout=10.0,
                    ),
                )
                response = client.models.generate_content(
                    model=self._model_name,
                    contents=prompt_content,
                    config=types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=AIExtractedBranch,
                    ),
                )
                if response.parsed and isinstance(response.parsed, AIExtractedBranch):
                    ai_extracted = response.parsed
                elif response.text:
                    parsed = json.loads(response.text)
                    ai_extracted = AIExtractedBranch(**parsed)
            except Exception as e:
                logger.warning(f"google-genai SDK call failed: {e}. Trying REST fallback...")

        # 2. REST API Fallback
        if ai_extracted is None:
            try:
                url = f"https://generativelanguage.googleapis.com/v1beta/models/{self._model_name}:generateContent"
                payload = {
                    "system_instruction": {"parts": [{"text": system_instruction}]},
                    "contents": [{"parts": [{"text": prompt_content}]}],
                    "generationConfig": {"response_mime_type": "application/json"},
                }
                req = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={
                        "Content-Type": "application/json",
                        "X-goog-api-key": self._api_key,
                    },
                )
                with urllib.request.urlopen(req, timeout=10) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    candidates = res_data.get("candidates", [])
                    if candidates:
                        parts = candidates[0].get("content", {}).get("parts", [])
                        if parts:
                            raw_text = parts[0].get("text", "").strip()
                            parsed_json = json.loads(raw_text)
                            ai_extracted = AIExtractedBranch(**parsed_json)
            except Exception as e:
                logger.warning(f"REST Gemini API fallback failed: {e}")

        if not ai_extracted:
            return None

        # Filter out negated/deprecated branches or low confidence inferences
        if ai_extracted.is_negated_or_deprecated:
            logger.info(f"AI flagged branch as negated/deprecated: {ai_extracted.reasoning}")
            return None

        if ai_extracted.confidence < 0.5:
            logger.info(f"AI confidence too low ({ai_extracted.confidence}): {ai_extracted.reasoning}")
            return None

        # Process PR number
        if ai_extracted.target_pr_number:
            pr_num = ai_extracted.target_pr_number
            target_ref = f"refs/pull/{pr_num}/head"
            return target_ref, {
                "ai_confidence": ai_extracted.confidence,
                "ai_reasoning": ai_extracted.reasoning,
                "pr_number": pr_num,
            }

        # Process branch name
        if ai_extracted.target_branch:
            try:
                sanitized = self.sanitize_branch_name(ai_extracted.target_branch)
                # Ground with Git remote verification
                if self.check_remote_branch_exists(backend_repo_url, sanitized):
                    return sanitized, {
                        "ai_confidence": ai_extracted.confidence,
                        "ai_reasoning": ai_extracted.reasoning,
                        "verified_on_remote": True,
                    }
                else:
                    logger.warning(
                        f"AI proposed branch '{sanitized}' does not exist on remote '{backend_repo_url}'."
                    )
            except ValueError as e:
                logger.warning(f"AI proposed branch failed sanitization: {e}")

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

        Enforces the Smart Hybrid resolution strategy:
        1. Fast Regex Match: If unambiguous & remote head exists -> Fast resolution (< 50ms).
        2. AI Intent Disambiguation: If regex match is negated/ambiguous or absent with conversational cues.
        3. Remote Branch Name Match: If identical branch exists on backend.
        4. Default Fallback: Fallback to 'dev' / 'main' with route-drift clarification.
        """
        sanitized_url = self.sanitize_repo_url(backend_repo_url)
        sanitized_source = self.sanitize_branch_name(source_branch)

        # Step 1: Regex Fast-Path Extraction
        explicit_linkage = self._extract_explicit_linkage(pr_body)
        if explicit_linkage:
            candidate_ref, details = explicit_linkage
            is_ambiguous = self._is_ambiguous_or_negated(pr_body or "", candidate_ref)

            if not is_ambiguous:
                logger.info(f"Resolved branch via Fast-Path Regex (Explicit PR Body): '{candidate_ref}'")
                return BranchResolutionResult(
                    target_branch=candidate_ref,
                    target_repo_url=sanitized_url,
                    source_branch=sanitized_source,
                    resolution_source=ResolutionSource.EXPLICIT_PR_BODY,
                    clarification_needed=False,
                    details=details,
                )

            logger.info(
                f"Candidate '{candidate_ref}' is ambiguous or negated in PR body. Consulting AI..."
            )
            # Try AI disambiguation
            ai_result = self.extract_branch_with_ai(pr_body or "", sanitized_url)
            if ai_result:
                ai_ref, ai_details = ai_result
                logger.info(f"Resolved branch via AI Disambiguation: '{ai_ref}'")
                return BranchResolutionResult(
                    target_branch=ai_ref,
                    target_repo_url=sanitized_url,
                    source_branch=sanitized_source,
                    resolution_source=ResolutionSource.AI_SEMANTIC_EXTRACTION,
                    clarification_needed=False,
                    details=ai_details,
                )

        # Step 2: Conversational Natural Language AI Extraction (when no regex matched)
        if pr_body and any(cue in pr_body.lower() for cue in CONVERSATIONAL_CUES):
            ai_result = self.extract_branch_with_ai(pr_body, sanitized_url)
            if ai_result:
                ai_ref, ai_details = ai_result
                logger.info(f"Resolved branch via AI Semantic Extraction: '{ai_ref}'")
                return BranchResolutionResult(
                    target_branch=ai_ref,
                    target_repo_url=sanitized_url,
                    source_branch=sanitized_source,
                    resolution_source=ResolutionSource.AI_SEMANTIC_EXTRACTION,
                    clarification_needed=False,
                    details=ai_details,
                )

        # Step 3: Remote Branch Name Matching
        if self.check_remote_branch_exists(sanitized_url, sanitized_source):
            logger.info(f"Resolved branch via Remote Branch Match: '{sanitized_source}'")
            return BranchResolutionResult(
                target_branch=sanitized_source,
                target_repo_url=sanitized_url,
                source_branch=sanitized_source,
                resolution_source=ResolutionSource.REMOTE_BRANCH_MATCH,
                clarification_needed=False,
                details={"matched_remote_head": f"refs/heads/{sanitized_source}"},
            )

        # Step 4: Default Fallback
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

        logger.info(f"Resolved branch via Default Fallback: '{fallback_target}'")
        return BranchResolutionResult(
            target_branch=fallback_target,
            target_repo_url=sanitized_url,
            source_branch=sanitized_source,
            resolution_source=ResolutionSource.DEFAULT_FALLBACK,
            clarification_needed=clarification_needed,
            clarification_message=clarification_message,
            details={"fallback_branch": fallback_target, "routes_flagged": new_backend_routes_detected},
        )
