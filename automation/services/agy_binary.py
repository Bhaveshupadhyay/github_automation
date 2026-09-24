"""Locates the Antigravity CLI (agy) binary."""
import logging
import os
import shutil
from typing import Optional

logger = logging.getLogger("automation.agy")


def find_agy_binary() -> Optional[str]:
    """Returns the agy binary from PATH or a standard install directory, or None when absent."""
    path_which = shutil.which("agy")
    if path_which and os.path.exists(path_which):
        return path_which

    home = os.path.expanduser("~")
    candidate_paths = [
        os.path.join(home, ".local", "bin", "agy"),
        os.path.join(home, ".gemini", "antigravity-cli", "bin", "agy"),
        os.path.join(home, ".gemini", "antigravity-cli", "agy"),
        "/usr/local/bin/agy",
        "/usr/bin/agy",
    ]
    for p in candidate_paths:
        if os.path.exists(p) and os.access(p, os.X_OK):
            logger.info(f"📍 Resolved agy binary at explicit path: {p}")
            return p

    return None
