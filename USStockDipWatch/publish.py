"""Publish only this project's static page to the existing shared web volume."""
import argparse
import json
import os
from pathlib import Path
import tempfile

PROJECT = Path(__file__).resolve().parent


def publish(site_root):
    target = Path(site_root) / "usstockdipwatch"
    target.mkdir(parents=True, exist_ok=True)
    html = (PROJECT / "web" / "index.html").read_text(encoding="utf-8")
    if "'/api/data'" in html or "/api/reminders" in html:
        raise RuntimeError("Page still contains the retired Sites API routes")
    # Atomic replacement avoids serving a half-written document.
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=target,
                                     prefix=".index-", delete=False) as stream:
        temp_path = Path(stream.name)
        stream.write(html)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        temp_path.chmod(0o644)
        os.replace(temp_path, target / "index.html")
    finally:
        temp_path.unlink(missing_ok=True)
    from collect import atomic_json
    atomic_json(target / "pe-history.json", json.loads((PROJECT / "web" / "pe-history.json").read_text()))
    initial = {"assets": [], "alerts": [], "healthy": 0, "expected": 5,
               "phase": "web-only", "scheduleEnabled": False}
    for name, contents in [("data.json", initial),
                           ("reminders.json", {"reminders": [], "configured": False}),
                           ("completions.json", {"records": [], "syncedAt": None})]:
        try:
            # Re-publishing must not erase existing data or alert history.
            with (target / name).open("x", encoding="utf-8") as stream:
                json.dump(contents, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            (target / name).chmod(0o644)
        except FileExistsError:
            pass
    print(f"Published page: {target / 'index.html'}")
    print("Phase 1 only: market collection, daily schedule, and phone reminders are not enabled.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--site-root", default=os.environ.get("VIBEQUANT_SITE_DIR", "/srv/web"))
    publish(parser.parse_args().site_root)
