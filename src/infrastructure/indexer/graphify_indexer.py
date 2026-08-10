import os
import subprocess
from src.domain.interfaces import IIndexerGateway
from src.core.logger import logger

def get_file_tree_summary(root_dir: str = ".") -> str:
    """Generates a compact relative file tree list for prompt context."""
    ignore_dirs = {".git", ".github", "__pycache__", "node_modules", "dist", "build", ".venv", "venv", "graphify-out", ".agents"}
    file_list = []
    
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            rel_path = os.path.relpath(os.path.join(root, file), root_dir)
            if not rel_path.startswith("."):
                file_list.append(rel_path)
                if len(file_list) > 100:
                    break
        if len(file_list) > 100:
            break
            
    return "\n".join(file_list)

class GraphifyIndexerAdapter(IIndexerGateway):
    """
    Adapter for querying Graphify knowledge graph CLI.
    Dynamically builds AST knowledge graph on the runner VM if not pre-existing.
    """

    def get_scoped_context(self, user_prompt: str) -> str:
        graph_path = os.path.join("graphify-out", "graph.json")
        wiki_index = os.path.join("graphify-out", "wiki", "index.md")
        
        # 1. Provide compact project file tree so AI doesn't waste turns stepping through folders
        file_tree = get_file_tree_summary()
        context = f"### Repository Project File Tree:\n{file_tree}\n"

        # 2. Dynamically build Graphify AST knowledge graph if missing
        if not os.path.exists(graph_path):
            logger.info("Generating Graphify AST knowledge graph dynamically on runner...")
            try:
                subprocess.run(["graphify", "update", "."], capture_output=True, text=True, check=True)
                logger.info("Graphify AST knowledge graph built successfully!")
            except Exception as e:
                logger.info(f"Graphify dynamic build skipped (CLI or dependencies not present): {e}")

        # 3. Query Graphify AST index for prompt context
        if os.path.exists(graph_path):
            logger.info("Querying Graphify AST index for relevant file graph...")
            try:
                res = subprocess.run(
                    ["graphify", "query", user_prompt],
                    capture_output=True, text=True, check=True
                )
                context += f"\n### Graphify Subgraph Context:\n{res.stdout}\n"
            except Exception as e:
                logger.warning(f"Graphify query failed, falling back to wiki index: {e}")
                if os.path.exists(wiki_index):
                    with open(wiki_index, "r", encoding="utf-8") as f:
                        context += f"\n### Graphify Wiki Index:\n{f.read()[:3000]}\n"

        return context
