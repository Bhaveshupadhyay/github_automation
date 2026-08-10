import os
import sys
import json
import time
import urllib.request
import urllib.error

def get_existing_repo_files(root_dir="."):
    ignore_dirs = {".git", ".github", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", "graphify-out"}
    existing = []
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for f in files:
            rel_path = os.path.relpath(os.path.join(root, f), root_dir)
            existing.append(rel_path)
    return existing

def match_target_filepath(raw_key, existing_files):
    if raw_key in existing_files:
        return raw_key

    norm_raw = raw_key.lower().replace(".py", "").replace(".js", "").replace(".ts", "").replace("_", "").replace("/", "").replace("\\", "")

    for target in existing_files:
        norm_target = target.lower().replace(".py", "").replace(".js", "").replace(".ts", "").replace("_", "").replace("/", "").replace("\\", "")
        if norm_raw and (norm_raw == norm_target or norm_raw in norm_target or norm_target in norm_raw):
            print(f"🎯 Matched key '{raw_key}' -> real repo file '{target}'")
            return target

    return raw_key

def parse_llm_files_dict(raw_files_obj, existing_files=None):
    if existing_files is None:
        existing_files = get_existing_repo_files()

    extracted = {}

    def recurse(node):
        if not isinstance(node, dict):
            return

        for k, v in node.items():
            if isinstance(v, str):
                if len(k) > 250:
                    continue

                matched_path = match_target_filepath(k, existing_files)

                if len(v) > len(k) and not v.startswith("app/") and not v.startswith("src/"):
                    extracted[matched_path] = v
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

def get_gemini_api_key():
    # 1. Environment Variable check
    for env_var in ["GEMINI_API_KEY", "AGY_API_KEY", "ANTIGRAVITY_API_KEY"]:
        val = os.getenv(env_var, "").strip()
        if val:
            print(f"Loaded API key from environment variable: {env_var}")
            return val

    # 2. Comprehensive search in ~/.gemini directory files
    gemini_dir = os.path.expanduser("~/.gemini")
    candidate_paths = [
        os.path.join(gemini_dir, "oauth_creds.json"),
        os.path.join(gemini_dir, "config", "config.json"),
        os.path.join(gemini_dir, "google_accounts.json"),
        os.path.join(gemini_dir, "settings.json"),
        os.path.join(gemini_dir, "state.json")
    ]

    for path in candidate_paths:
        if os.path.exists(path):
            try:
                with open(path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        token = data.get("access_token") or data.get("api_key") or data.get("token") or data.get("key")
                        if token:
                            print(f"Loaded credentials from: {path}")
                            return token
            except Exception as e:
                print(f"Warning reading {path}: {e}")

    return ""

def execute_api_call(payload, api_key, model="gemini-3.5-flash-lite"):
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={api_key}"
    headers = {"Content-Type": "application/json"}
    if api_key.startswith("ya29."):
        # If it's an OAuth bearer token
        headers["Authorization"] = f"Bearer {api_key}"
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"

    req = urllib.request.Request(url, data=payload, headers=headers)
    
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code == 429:
                wait_time = (2 ** attempt) + 2
                print(f"Rate limited (429). Retrying in {wait_time}s...")
                time.sleep(wait_time)
            elif e.code == 404:
                print(f"Model {model} 404. Failing over to gemini-3.6-flash...")
                model = "gemini-3.6-flash"
                url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-3.6-flash:generateContent?key={api_key}"
                req = urllib.request.Request(url, data=payload, headers=headers)
            else:
                raise Exception(f"HTTP Error {e.code}: {e.read().decode('utf-8', errors='ignore')}")

    raise Exception("API call failed after retries.")

def run_agent(user_prompt):
    api_key = get_gemini_api_key()
    if not api_key:
        print("ERROR: No valid GEMINI_API_KEY / AGY_API_KEY or restored ~/.gemini credentials found.")
        sys.exit(1)

    existing_files = get_existing_repo_files()
    file_tree = "\n".join(existing_files[:100])

    tools = [{
        "function_declarations": [
            {
                "name": "read_file",
                "description": "Read file content",
                "parameters": {
                    "type": "OBJECT",
                    "properties": {"filepath": {"type": "STRING"}},
                    "required": ["filepath"]
                }
            },
            {
                "name": "list_directory",
                "description": "List files in directory",
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
                        "files": {
                            "type": "OBJECT",
                            "description": "Flat JSON object mapping file paths to new complete content."
                        },
                        "commit_message": {"type": "STRING"}
                    },
                    "required": ["files", "commit_message"]
                }
            }
        ]
    }]

    system_instruction = (
        "You are an elite Senior Principal Software Engineer.\n"
        "Your task: Implement complete code changes for the user request.\n"
        "RULES:\n"
        "1. If request lacks essential info, output 'CLARIFICATION_NEEDED: <question>'.\n"
        "2. Update existing files in place using exact relative path keys (e.g., 'app/api/v1/post.py').\n"
        "3. Invoke 'apply_changes' with your modifications as soon as ready."
    )

    context = f"### Repository File Tree:\n{file_tree}\n"
    contents = [{
        "role": "user",
        "parts": [{"text": f"{system_instruction}\n\nUser Request: {user_prompt}\n\n{context}"}]
    }]

    modified_files = {}
    commit_msg = f"AI Update: {user_prompt}"

    for turn in range(15):
        payload = json.dumps({"contents": contents, "tools": tools}).encode("utf-8")
        response = execute_api_call(payload, api_key)

        candidate = response.get("candidates", [{}])[0]
        parts = candidate.get("content", {}).get("parts", [])

        function_call = None
        for part in parts:
            if "functionCall" in part:
                function_call = part["functionCall"]
                break

        if not function_call:
            if not modified_files and turn < 14:
                print("Model output text instead of function call. Requesting tool execution...")
                contents.append({"role": "model", "parts": parts})
                contents.append({
                    "role": "user",
                    "parts": [{"text": "Call 'apply_changes' tool NOW with files={'filepath': 'code...'}"}]
                })
                continue
            else:
                print("Agent loop completed.")
                break

        fn_name = function_call["name"]
        fn_args = function_call.get("args", {})
        print(f"🤖 Tool call (Turn {turn + 1}/15): {fn_name}({fn_args})")

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
            modified_files = parse_llm_files_dict(raw_files, existing_files=existing_files)
            print(f"Agent submitted changes for {len(modified_files)} files: {list(modified_files.keys())}")
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

    # Write modifications to disk
    for filepath, content in modified_files.items():
        if os.path.isdir(filepath):
            continue
        dir_name = os.path.dirname(filepath)
        if dir_name:
            os.makedirs(dir_name, exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"Successfully updated file: {filepath}")

if __name__ == "__main__":
    prompt_arg = sys.argv[1] if len(sys.argv) > 1 else os.getenv("USER_PROMPT", "")
    if prompt_arg:
        run_agent(prompt_arg)
    else:
        print("No prompt provided.")
