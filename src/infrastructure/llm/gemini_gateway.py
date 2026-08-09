import os
import json
import urllib.request
from src.domain.interfaces import ILLMGateway
from src.domain.entities import CodeModification
from src.core.exceptions import LLMGenerationError

class GeminiLLMAdapter(ILLMGateway):
    """Adapter for Google Gemini API using Function Calling (Tool Use)."""

    def __init__(self, api_key: str, model_name: str = "gemini-2.0-flash"):
        self.api_key = api_key
        self.model_name = model_name

    def generate_code_changes(self, user_prompt: str, context: str) -> CodeModification:
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model_name}:generateContent?key={self.api_key}"
        
        tools = [{
            "function_declarations": [
                {
                    "name": "read_file",
                    "description": "Read content of a specific file",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {"filepath": {"type": "STRING"}},
                        "required": ["filepath"]
                    }
                },
                {
                    "name": "list_directory",
                    "description": "List files in a directory",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {"dirpath": {"type": "STRING"}},
                        "required": ["dirpath"]
                    }
                },
                {
                    "name": "apply_changes",
                    "description": "Submit code changes",
                    "parameters": {
                        "type": "OBJECT",
                        "properties": {
                            "files": {"type": "OBJECT"},
                            "commit_message": {"type": "STRING"}
                        },
                        "required": ["files", "commit_message"]
                    }
                }
            ]
        }]

        system_instruction = (
            "You are an expert AI software engineer.\n"
            "Use graphify context and directory listing tools to read ONLY relevant files.\n"
            "Once ready, invoke 'apply_changes' with your modifications."
        )

        contents = [{
            "role": "user",
            "parts": [{"text": f"{system_instruction}\n\nUser Prompt: {user_prompt}\n{context}"}]
        }]

        modified_files = {}
        commit_msg = f"AI Update: {user_prompt}"

        for turn in range(5):
            payload = json.dumps({"contents": contents, "tools": tools}).encode("utf-8")
            req = urllib.request.Request(url, data=payload, headers={"Content-Type": "application/json"})
            
            try:
                with urllib.request.urlopen(req) as resp:
                    response = json.loads(resp.read().decode("utf-8"))
            except Exception as e:
                raise LLMGenerationError(f"Gemini API call failed: {e}")

            candidate = response["candidates"][0]
            parts = candidate.get("content", {}).get("parts", [])

            function_call = None
            for part in parts:
                if "functionCall" in part:
                    function_call = part["functionCall"]
                    break

            if not function_call:
                break

            fn_name = function_call["name"]
            fn_args = function_call.get("args", {})
            print(f"🤖 Tool call: {fn_name}({fn_args})")

            tool_result = {}
            if fn_name == "read_file":
                path = fn_args.get("filepath", "")
                if os.path.exists(path):
                    with open(path, "r", encoding="utf-8") as f:
                        tool_result = {"content": f.read()}
                else:
                    tool_result = {"error": f"File {path} not found"}

            elif fn_name == "list_directory":
                path = fn_args.get("dirpath", ".")
                if os.path.exists(path):
                    tool_result = {"files": os.listdir(path)}
                else:
                    tool_result = {"error": f"Directory {path} not found"}

            elif fn_name == "apply_changes":
                modified_files = fn_args.get("files", {})
                commit_msg = fn_args.get("commit_message", commit_msg)
                break

            contents.append({"role": "model", "parts": parts})
            contents.append({
                "role": "function",
                "parts": [{"functionResponse": {"name": fn_name, "response": tool_result}}]
            })

        return CodeModification(files=modified_files, commit_message=commit_msg)
