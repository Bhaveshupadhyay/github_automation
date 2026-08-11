import os
import shutil
import subprocess

class WorkspaceCleanupService:
    """Service responsible for stripping temporary files so they are excluded from PR diffs."""
    
    @staticmethod
    def cleanup_unwanted_files():
        print("🧹 Cleaning up injected .agents, rules, skills, and graphify files...")
        unwanted_paths = [".agents", "graphify-out", "graphify_context.txt"]
        
        for path in unwanted_paths:
            if os.path.exists(path):
                if os.path.isdir(path):
                    shutil.rmtree(path, ignore_errors=True)
                else:
                    try:
                        os.remove(path)
                    except OSError:
                        pass
        
        subprocess.run(["git", "checkout", "--", ".agents"], capture_output=True, text=True)
