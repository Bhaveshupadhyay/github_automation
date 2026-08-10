import os
import json
import time
import urllib.request
import urllib.error
from src.domain.interfaces import ILLMGateway
from src.domain.entities import CodeModification
from src.core.exceptions import LLMGenerationError
from src.core.logger import logger

def get_existing_repo_files(root_dir: str = ".") -> list:
    """Scans disk to get a list of all existing relative file paths in workspace."""
    ignore_dirs = {".git", ".github", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", "graphify-out"}
    existing = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), root_dir)
            existing.append(rel_path)
    return existing

def match_target_filepath(raw_key: str, existing_files: list) -> str:
    """
    Fuzzy matches mangled keys (e.g. 'app_api_v1_post', 'uappauapiuv1upostupyy')
    against actual existing file paths in the workspace.
    """
    if raw_key in existing_files:
        return raw_key

    # Normalize key by removing extensions and converting underscores/slashes
    norm_raw = raw_key.lower().replace(".py", "").replace(".js", "").replace(".ts", "").replace("_", "").replace("/", "").replace("\\", "")

    best_match = None
    for target in existing_files:
        norm_target = target.lower().replace(".py", "").replace(".js", "").replace(".ts", "").replace("_", "").replace("/", "").replace("\\", "")
        
        # If normalized string matches existing file path
        if norm_raw and (norm_raw == norm_target or norm_raw in norm_target or norm_target in norm_raw):
            logger.info(f"🎯 Matched mangled key '{raw_key}' -> real repo file '{target}'")
            return target

    return raw_key

def parse_llm_files_dict(raw_files_obj, existing_files: list = None) -> dict:
    """
    Robust recursive parser that extracts (filepath -> code_content) 
    and resolves mangled keys against actual existing repo files on disk.
    """
    if existing_files is None:
        existing_files = get_existing_repo_files()

    extracted = {}

    def recurse(node):
        if not isinstance(node, dict):
            return

        for k, v in node.items():
            if isinstance(v, str):
                if len(k) > 250:
                    logger.warning(f"Discarding invalid long key of length {len(k)}")
                    continue

                matched_path = match_target_filepath(k, existing_files)

                # Case 1: Value is code content
                if len(v) > len(k) and not v.startswith("app/") and not v.startswith("src/"):
                    extracted[matched_path] = v
                # Case 2: Value contains "filepath:code"
                elif ":" in v and len(v.split(":", 1)[0]) < 250 and ("/" in v.split(":", 1)[0] or "." in v.split(":", 1)[0]):
                    parts = v.split(":", 1)
                    fp = match_target_filepath(parts[0].strip(), existing_files)
                    content = parts[1].lstrip()
                    extracted[fp] = content
                else:
                    extracted[matched_path] = v
            elif isinstance(v, dict):
                recurse(v)

    recurse(raw_files_obj)
    return extracted

class GeminiLLMAdapter(ILLMGateway):
    """
    Adapter for Google Gemini API using Function Calling (Tool Use)
    with Multi-Model Fallback and Exponential Backoff.
    """

    DEFAULT_FALLBACK_MODELS = [
        "gemini-3.5-flash-lite",
        "gemini-3.6-flash",
        "gemini-3.1-flash-lite",
        "gemini-2.0-flash",
        "gemini-flash-latest"
    ]

    def __init__(self, api_key: str, model_name: str = "gemini-3.5-flash-lite", max_retries_per_model: int = 2, max_turns: int = 25):
        self.api_key = api_key
        self.primary_model = model_name or "gemini-3.5-flash-lite"
        self.max_retries_per_model = max_retries_per_model
        self.max_turns = max_turns

    def _execute_api_call_with_fallback(self, payload: bytes) -> dict:
        """Executes API request with multi-model fallback & retries on HTTP 429 / 404 / rate limits."""
        models_to_try = [self.primary_model] + [m for m in self.DEFAULT_FALLBACK_MODELS if m != self.primary_model]

        for model in models_to_try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={self.api_key}"
            
            for attempt in range(self.max_retries_per_model):
                req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
                try:
                    with urllib.request.urlopen(req) as resp:
                        return json.loads(resp.read().decode("utf-8"))
                except urllib.error.HTTPError as e:
                    if e.code == 429:
                        wait_time = (2 ** attempt) + 2
                        logger.warning(
                            f"Model '{model}' returned HTTP 429 (Rate Limit). "
                            f"Retrying attempt {attempt + 1}/{self.max_retries_per_model} in {wait_time}s..."
                        )
                        time.sleep(wait_time)
                    elif e.code == 404:
                        logger.warning(f"Model '{model}' returned HTTP 404. Skipping to next model...")
                        break
                    elif e.code in (500, 503):
                        time.sleep(2)
                    else:
                        error_body = e.read().decode('utf-8', errors='ignore')
                        logger.error(f"Gemini API Fatal Error HTTP {e.code}: {error_body}")
                        raise LLMGenerationError(f"Gemini API Error HTTP {e.code}: {error_body}")
                except Exception as e:
                    logger.error(f"Network error communicating with Gemini API: {e}")
                    raise LLMGenerationError(f"Network Error: {e}")

        raise LLMGenerationError("All Gemini fallback models were rate-limited. Please wait 30 seconds for quota reset.")

    def generate_code_changes(self, user_prompt: str, context: str) -> CodeModification:
        tools = [{
            "function_declarations": [
                {
                    "name": "read_file",
                    "description": "Read content of a specific file in the project (including skills in .agents/skills/)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {"filepath": {"type": "STRING"}},
                        "required": ["filepath"]
                    }
                },
                {
                    "name": "list_directory",
                    "description": "List files in a directory (such as .agents/skills or src)",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {"dirpath": {"type": "STRING"}},
                        "required": ["dirpath"]
                    }
                },
                {
                    "name": "apply_changes",
                    "description": "Submit final complete code modifications.",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "files": {
                                "type": "OBJECT",
                                "description": "Flat JSON object mapping exact relative file paths to full source code string (e.g. {'app/api/v1/post.py': 'from fastapi import...'})."
                            },
                            "commit_message": {"type": "STRING", "description": "Concise git commit summary"}
                        },
                        "required": ["files", "commit_message"]
                    }
                }
            ]
        }]

        system_instruction = (
            "You are an elite Senior Principal Software Engineer.\n"
            "Your MANDATORY TASK: Implement complete, production-ready source code changes for the user's request.\n\n"
            "RULES FOR APPLY_CHANGES:\n"
            "1. You MUST update existing files in the repo (e.g. 'app/api/v1/post.py'). Do NOT invent new mangled filenames like 'app_api_v1_post'.\n"
            "2. In apply_changes(files={...}), the dictionary KEY must be the EXACT relative filepath string (e.g., 'app/api/v1/post.py').\n"
            "3. The dictionary VALUE must be the FULL updated code content string of that file."
        )

        contents = [{
            "role": "user",
            "parts": [{"text": f"{system_instruction}\n\nUser Request: {user_prompt}\n\n{context}"}]
        }]

        modified_files = {}
        commit_msg = f"AI Update: {user_prompt}"

        for turn in range(self.max_turns):
            payload = json.dumps({"contents": contents, "tools": tools}).encode("utf-8")
            
            response = self._execute_api_call_with_fallback(payload)

            candidate = response.get("candidates", [{}])[0]
            parts = candidate.get("content", {}).get("parts", [])

            function_call = None
            text_response = ""
            for part in parts:
                if "functionCall" in part:
                    function_call = part["functionCall"]
                if "text" in part:
                    text_response += part["text"]

            if not function_call:
                if not modified_files and turn < (self.max_turns - 1):
                    logger.warning("Agent responded with text instead of calling apply_changes. Prompting agent to submit code edits...")
                    contents.append({"role": "model", "parts": parts})
                    contents.append({
                        "role": "user",
                        "parts": [{"text": "Do NOT reply with plain text. Call the 'apply_changes' tool NOW with files={'filepath': 'code...'}"}]
                    })
                    continue
                else:
                    logger.info("Agent turn completed.")
                    break

            fn_name = function_call["name"]
            fn_args = function_call.get("args", {})
            logger.info(f"🤖 Tool call (Turn {turn + 1}/{self.max_turns}): {fn_name}({fn_args})")

            tool_result = {}
            if fn_name == "read_file":
                path = fn_args.get("filepath", "")
                if os.path.exists(path) and os.path.isfile(path):
                    with open(path, "r", encoding="utf-8") as f:
                        tool_result = {"content": f.read()}
                else:
                    tool_result = {"error": f"File {path} not found"}

            elif fn_name == "list_directory":
                path = fn_args.get("dirpath", ".")
                if os.path.exists(path) and os.path.isdir(path):
                    tool_result = {"files": os.listdir(path)}
                else:
                    tool_result = {"error": f"Directory {path} not found"}

            elif fn_name == "apply_changes":
                raw_files = fn_args.get("files", {})
                commit_msg = fn_args.get("commit_message", commit_msg)
                
                existing_files = get_existing_repo_files()
                modified_files = parse_llm_files_dict(raw_files, existing_files=existing_files)
                logger.info(f"Agent submitted changes for {len(modified_files)} files: {list(modified_files.keys())}")
                break

            contents.append({"role": "model", "parts": parts})
            contents.append({
                "role": "user",
                "parts": [{
                    "functionResponse": {
                        "name": fn_name,
                        "response": tool_result
                    }
                }]
            })

            time.sleep(1.5)

        return CodeModification(files=modified_files, commit_message=commit_msg)
