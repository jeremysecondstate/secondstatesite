"""Prepare auditable ESM copies for supported runtimes that cannot import CJS."""

import argparse
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path


def digest(data):
    return sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    parser.add_argument("--repo", type=Path, default=Path("C:/dev/secondstatesite"))
    args = parser.parse_args()
    source_dir = args.repo / "scripts"
    collector_path = source_dir / "invaluable_browser_collection.cjs"
    core_path = source_dir / "invaluable_export_snapshot.js"
    collector_bytes, core_bytes = collector_path.read_bytes(), core_path.read_bytes()
    collector, core = collector_bytes.decode("utf-8"), core_bytes.decode("utf-8")
    marker = "module.exports = ("
    if collector.count(marker) != 1:
        raise ValueError("Collector export changed; inspect it before adapting.")
    if "module.exports = core;" not in core or 'typeof document === "undefined"' not in core:
        raise ValueError("Snapshot core export changed; inspect it before adapting.")
    outputs = [
        (collector_path, collector_bytes, "invaluable-browser-collection.mjs",
         collector.replace(marker, "export default (", 1).encode("utf-8"),
         "Replace the sole CJS factory export with an ESM default export."),
        (core_path, core_bytes, "invaluable-snapshot-core.mjs",
         ("const module = { exports: {} };\n" + core + "\nexport default module.exports;\n").encode("utf-8"),
         "Wrap unchanged snapshot source in a local module object and export its core."),
    ]
    manifest_path = args.run_dir / "module-provenance.json"
    paths = [args.run_dir / entry[2] for entry in outputs] + [manifest_path]
    if any(path.exists() for path in paths):
        raise FileExistsError("Use a fresh attempt directory; preserve prior prepared modules.")
    args.run_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for source, original, name, prepared, description in outputs:
        destination = args.run_dir / name
        with destination.open("xb") as handle:
            handle.write(prepared)
        records.append({"source": str(source.resolve()), "source_sha256": digest(original),
                        "prepared": str(destination.resolve()), "prepared_sha256": digest(prepared),
                        "transformation": description})
    with manifest_path.open("x", encoding="utf-8") as handle:
        json.dump({"format": "secondstate-browser-module-provenance-v1",
                   "prepared_at": datetime.now(timezone.utc).isoformat(), "modules": records},
                  handle, ensure_ascii=False, indent=2)
    print(json.dumps({"manifest": str(manifest_path.resolve()), "modules": len(records)}))


if __name__ == "__main__":
    main()
