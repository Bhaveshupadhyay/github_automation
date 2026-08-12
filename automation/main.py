import sys
import logging
from automation.core import get_orchestration_service

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S"
)

def main():
    orchestrator = get_orchestration_service()
    success = orchestrator.run()
    if not success:
        sys.exit(1)

if __name__ == "__main__":
    main()
