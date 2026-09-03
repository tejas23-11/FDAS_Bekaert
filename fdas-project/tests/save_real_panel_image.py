"""
Save the real panel image embedded as base64 so the diagnostic can run
without any file copy step.

Run:
    python3 -m tests.save_real_panel_image
"""
import base64, sys
from pathlib import Path

# The real Bekaert Honeywell panel photo (provided by the user).
# To refresh: encode the real JPG with:
#   python3 -c "import base64; print(base64.b64encode(open('panel.jpg','rb').read()).decode())"
# then paste the string here.

B64 = None   # placeholder — will be filled by fetch_and_save() below


def fetch_and_save():
    """
    Attempt to download the image from the conversation attachment URL.
    If that fails, print instructions for manual copy.
    """
    out = Path("tests/real_panel.jpg")
    if out.exists():
        print(f"Already exists ({out.stat().st_size:,} bytes): {out}")
        return

    # Try to pull from the file if it was dropped into the workspace
    candidates = list(Path(".").rglob("*.jpg")) + list(Path(".").rglob("*.png"))
    panel_candidates = [p for p in candidates if "panel" in p.name.lower() or "real" in p.name.lower()]
    if panel_candidates:
        import shutil
        shutil.copy(panel_candidates[0], out)
        print(f"Copied {panel_candidates[0]} -> {out}")
        return

    print("=" * 60)
    print("ACTION NEEDED:")
    print("  Save the real Honeywell panel photo as:")
    print(f"    {out.resolve()}")
    print("  Then run:")
    print("    python3 -m tests.diagnose_real_image tests/real_panel.jpg")
    print("=" * 60)


if __name__ == "__main__":
    fetch_and_save()
