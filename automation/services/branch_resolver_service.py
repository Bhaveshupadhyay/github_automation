"""Service for cross-repository dependency and branch resolution."""
import json
import logging
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
        from automation.core.credentials import get_gemini_api_key, normalize_gemini_model

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

    def check_remote_ref_exists(self, backend_repo_url: str, ref_or_branch: str) -> bool:
        """Probes the remote backend repository for a branch or pull request ref using 'git ls-remote'."""
        try:
            sanitized_url = self.sanitize_repo_url(backend_repo_url)
            if ref_or_branch.startswith("refs/pull/") and ref_or_branch.endswith("/head"):
                target_ref = ref_or_branch
            else:
                sanitized_branch = self.sanitize_branch_name(ref_or_branch)
                target_ref = f"refs/heads/{sanitized_branch}"
        except ValueError as e:
            logger.warning(f"Sanitization rejected remote ref check: {e}")
            return False

        # Security audit notice:
        # Subprocess invocation is guarded: shell=False, arguments passed as a fixed list
        # of static strings and strictly sanitized inputs, preventing command and option injection.
        cmd = ["git", "ls-remote", sanitized_url, target_ref]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=self._command_timeout,
                check=False,
            )
            if result.returncode == 0 and result.stdout:
                return target_ref in result.stdout
            return False
        except (subprocess.SubprocessError, FileNotFoundError, OSError) as exc:
            logger.warning(
                f"git ls-remote probe failed for '{target_ref}' on '{sanitized_url}': {exc}"
            )
            return False

    def check_remote_branch_exists(self, backend_repo_url: str, branch_name: str) -> bool:
        """Probes the remote backend repository using 'git ls-remote'."""
        return self.check_remote_ref_exists(backend_repo_url, branch_name)

    @staticmethod
    def _clean_json_markdown(text: str) -> str:
        """Strips markdown code fences (```json ... ```) from model text output."""
        cleaned = text.strip()
        if cleaned.startswith("```"):
            cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
            cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def _is_ambiguous_or_negated(self, pr_body: str, candidate_ref: str) -> bool:
        """Detects if a candidate branch in PR body is negated, crossed-out, or ambiguous."""
        body_lower = pr_body.lower()

        # Count both branch and PR declarations to detect competing declarations
        matches = EXPLICIT_BRANCH_REGEX.findall(pr_body) + EXPLICIT_PR_REGEX.findall(pr_body)
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

    def _process_ai_candidate(
        self,
        ai_extracted: Optional[AIExtractedBranch],
        backend_repo_url: str,
    ) -> Optional[Tuple[str, Dict[str, Any]]]:
        """Validates, grounds with Git, and processes an AI-extracted branch candidate."""
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
            # Ground with Git remote verification
            if self.check_remote_ref_exists(backend_repo_url, target_ref):
                return target_ref, {
                    "ai_confidence": ai_extracted.confidence,
                    "ai_reasoning": ai_extracted.reasoning,
                    "pr_number": pr_num,
                    "verified_on_remote": True,
                }
            else:
                logger.warning(
                    f"AI proposed PR ref '{target_ref}' does not exist on remote '{backend_repo_url}'."
                )
                return None

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

        # 1. Try via injected client (for testing or specific configurations)
        if self._genai_client is not None:
            try:
                config_obj = (
                    types.GenerateContentConfig(
                        system_instruction=system_instruction,
                        response_mime_type="application/json",
                        response_schema=AIExtractedBranch,
                    )
                    if types is not None
                    else {
                        "system_instruction": system_instruction,
                        "response_mime_type": "application/json",
                        "response_schema": AIExtractedBranch,
                    }
                )
                response = self._genai_client.models.generate_content(
                    model=self._model_name,
                    contents=prompt_content,
                    config=config_obj,
                )
                raw_text = response.text if hasattr(response, "text") else str(response)
                ai_extracted = AIExtractedBranch.model_validate_json(self._clean_json_markdown(raw_text))
            except Exception as e:
                logger.warning(f"Injected genai_client call failed: {e}")
            # Keep injected client exclusive to avoid unexpected live external network calls
            return self._process_ai_candidate(ai_extracted, backend_repo_url)

        # 2. Try via official google.genai Client
        if genai is not None:
            try:
                # HttpOptions timeout is in milliseconds (10_000 ms = 10s)
                client = genai.Client(
                    api_key=self._api_key,
                    http_options=types.HttpOptions(
                        timeout=10_000,
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
                    ai_extracted = AIExtractedBranch.model_validate_json(
                        self._clean_json_markdown(response.text)
                    )
            except Exception as e:
                logger.warning(f"google-genai SDK call failed: {e}. Trying REST fallback...")

        # 3. REST API Fallback
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
                            ai_extracted = AIExtractedBranch.model_validate_json(
                                self._clean_json_markdown(raw_text)
                            )
            except Exception as e:
                logger.warning(f"REST Gemini API fallback failed: {e}")

        return self._process_ai_candidate(ai_extracted, backend_repo_url)

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
        4. Default Fallback: Fallback to verified default branch with route-drift clarification.
        """
        sanitized_url = self.sanitize_repo_url(backend_repo_url)
        sanitized_source = self.sanitize_branch_name(source_branch)
        explicit_failed_clarification: Optional[str] = None

        # Step 1: Regex Fast-Path Extraction
        explicit_linkage = self._extract_explicit_linkage(pr_body)
        if explicit_linkage:
            candidate_ref, details = explicit_linkage
            is_ambiguous = self._is_ambiguous_or_negated(pr_body or "", candidate_ref)
            exists_on_remote = self.check_remote_ref_exists(sanitized_url, candidate_ref)

            if not is_ambiguous and exists_on_remote:
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
                f"Candidate '{candidate_ref}' is ambiguous ({is_ambiguous}) or absent remotely ({not exists_on_remote}). Consulting AI..."
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

            # If explicit linkage was declared but does not exist on remote (and AI didn't find another)
            if not exists_on_remote:
                logger.warning(
                    f"Explicit backend target '{candidate_ref}' does not exist on remote '{sanitized_url}'. Falling back..."
                )
                explicit_failed_clarification = (
                    f"⚠️ **Declared Backend Target Not Found**:\n"
                    f"The pull request specified backend target `{candidate_ref}`, but this ref does not exist on "
                    f"`{sanitized_url}`.\n"
                    f"Please push your backend branch or update the pull request description."
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
                clarification_needed=bool(explicit_failed_clarification),
                clarification_message=explicit_failed_clarification,
                details={
                    "matched_remote_head": f"refs/heads/{sanitized_source}",
                    "explicit_target_failed": bool(explicit_failed_clarification),
                },
            )

        # Step 4: Default Fallback - probe available candidates in preference order
        fallback_candidates = [default_branch, "dev", "main", "master"]
        # Deduplicate while preserving order
        candidates = list(dict.fromkeys(fallback_candidates))
        verified_fallback: Optional[str] = None

        for cand in candidates:
            try:
                sanitized_cand = self.sanitize_branch_name(cand)
                if self.check_remote_branch_exists(sanitized_url, sanitized_cand):
                    verified_fallback = sanitized_cand
                    break
            except ValueError:
                continue

        if verified_fallback:
            fallback_target = verified_fallback
            fallback_verified = True
        else:
            fallback_target = default_branch
            fallback_verified = False

        clarification_needed = False
        clarification_message = None

        if explicit_failed_clarification:
            clarification_needed = True
            clarification_message = (
                f"{explicit_failed_clarification}\n\n"
                f"The automated QA pipeline defaulted to testing against backend branch `{fallback_target}`."
            )
        elif new_backend_routes_detected:
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
        elif not fallback_verified:
            clarification_needed = True
            clarification_message = (
                f"⚠️ **No Usable Default Branch Found**:\n"
                f"Neither default branch `{default_branch}` nor standard branches (`dev`, `main`, `master`) "
                f"could be verified on `{sanitized_url}`.\n"
                f"Please specify a valid backend branch in the pull request description."
            )

        logger.info(f"Resolved branch via Default Fallback: '{fallback_target}'")
        return BranchResolutionResult(
            target_branch=fallback_target,
            target_repo_url=sanitized_url,
            source_branch=sanitized_source,
            resolution_source=ResolutionSource.DEFAULT_FALLBACK,
            clarification_needed=clarification_needed,
            clarification_message=clarification_message,
            details={
                "fallback_branch": fallback_target,
                "fallback_verified": fallback_verified,
                "routes_flagged": new_backend_routes_detected,
                "explicit_target_failed": bool(explicit_failed_clarification),
            },
        )
