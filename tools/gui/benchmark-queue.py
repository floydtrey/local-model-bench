"""Run the GUI directly from a checkout; no editable install is necessary."""
from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "src"))

if __name__ == "__main__":
    try:
        from localbench.queue_gui.app import main
    except ImportError as exc:
        raise SystemExit(f"Cannot load the queue GUI: {exc}\nUse Python 3.10+ with Tcl/Tk (included in the standard Windows Python installer).") from exc
    raise SystemExit(main())
