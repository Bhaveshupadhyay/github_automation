import os
import subprocess
from src.domain.interfaces import IIndexerGateway

class GraphifyIndexerAdapter(IIndexerGateway):
    """Adapter for querying Graphify knowledge graph CLI."""

    def get_scoped_context(self, user_prompt: str) -> str:
        graph_path = os.path.join("graphify-out", "graph.json")
        wiki_index = os.path.join("graphify-out", "wiki", "index.md")
        
        context = ""
        if os.path.exists(graph_path):
            print("🔍 Found graphify-out/graph.json! Querying sub-graph...")
            try:
                res = subprocess.run(
                    ["graphify", "query", user_prompt],
                    capture_output=True, text=True, check=True
                )
                context += f"\n### Graphify Subgraph Context:\n{res.stdout}\n"
            except Exception:
                if os.path.exists(wiki_index):
                    with open(wiki_index, "r", encoding="utf-8") as f:
                        context += f"\n### Graphify Wiki Index:\n{f.read()[:3000]}\n"
        return context
