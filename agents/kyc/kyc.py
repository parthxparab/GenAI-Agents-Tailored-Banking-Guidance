from pathlib import Path
import sys

if __package__ in (None, ""):
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.append(str(project_root))

from agents.kyc.kyc_agent import run


if __name__ == "__main__":
    run()
