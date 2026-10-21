"""Build the unpacked Chrome/Edge collector with the shared snapshot validator."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import shutil
import zipfile


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "browser_extensions" / "invaluable_collector"
DEFAULT_OUTPUT = ROOT / "private_data" / "invaluable-collector"


def build(output: Path) -> tuple[Path, Path]:
    output = output.resolve()
    if output == SOURCE.resolve() or SOURCE.resolve() in output.parents:
        raise ValueError("Choose a build directory outside the extension source folder.")
    manifest = json.loads((SOURCE / "manifest.json").read_text(encoding="utf-8"))
    files = [path for path in SOURCE.iterdir() if path.is_file() and path.suffix in {".json", ".js", ".html", ".css"}]
    names = {path.name for path in files} | {"snapshot-core.js"}
    references = [manifest["background"]["service_worker"], manifest["action"]["default_popup"]]
    for script in manifest.get("content_scripts", []):
        references.extend(script.get("js", []))
        references.extend(script.get("css", []))
    if any(name not in names for name in references):
        raise ValueError("The extension manifest refers to a missing packaged file.")
    output.mkdir(parents=True, exist_ok=True)
    for path in files:
        shutil.copyfile(path, output / path.name)
    shutil.copyfile(ROOT / "scripts" / "invaluable_export_snapshot.js", output / "snapshot-core.js")
    archive = output.with_name(output.name + ".zip")
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as bundle:
        for name in sorted(names):
            bundle.write(output / name, arcname=f"invaluable-collector/{name}")
    return output, archive


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    folder, archive = build(args.output)
    print(f"Load unpacked: {folder}\nZIP: {archive}")
