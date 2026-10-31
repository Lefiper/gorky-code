"""Изменённые исходники относительно ранее переданного ZIP, без локальных секретов."""

import argparse
import hashlib
import json
from pathlib import Path
import zipfile

from scripts.package_release import ROOT, main as package_full


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--baseline", default="dist/assistant-storage-mcp-before-2026-10-26.zip")
    parser.add_argument("--label", default="2026-10-26")
    args = parser.parse_args()
    if any(char not in "0123456789-" for char in args.label) or not args.label:
        parser.error("label должен быть датой YYYY-MM-DD")
    baseline = ROOT / args.baseline
    package_full()
    current = ROOT / "dist/assistant-storage-mcp.zip"
    output = ROOT / f"dist/assistant-storage-update-{args.label}.zip"
    with zipfile.ZipFile(baseline) as old, zipfile.ZipFile(current) as new:
        old_names, new_names = set(old.namelist()), set(new.namelist())
        changed = sorted(name for name in new_names if name not in old_names or old.read(name) != new.read(name))
        removed = sorted(old_names - new_names)
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as patch:
            for name in changed:
                patch.writestr(name, new.read(name))
    manifest = {"baseline": baseline.name, "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
                "changed_files": changed, "removed_files": removed,
                "note": "Compare with your Git branch before copying; this is relative to the previous source archive, not the live team repository."}
    (ROOT / f"dist/update-manifest-{args.label}.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Update archive: {output.name}, {len(changed)} changed/new source files; {len(removed)} removals listed in manifest.")


if __name__ == "__main__":
    main()
