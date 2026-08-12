import os
import shutil
import logging

logger = logging.getLogger("automation.cleanup")

class WorkspaceCleanupService:
    """Service responsible for stripping temporary files so they are excluded from PR diffs."""
    
    @staticmethod
    def cleanup_unwanted_files():
        logger.info("🧹 Cleaning up temporary graphify context and log files...")
        unwanted_paths = ["graphify-out", "graphify_context.txt"]
        
        for path in unwanted_paths:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
