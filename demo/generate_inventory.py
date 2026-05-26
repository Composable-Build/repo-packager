#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    import subprocess
    subprocess.run([sys.executable, "-m", "pip", "install", "pyyaml", "-q"], check=True)
    import yaml

ROOT = Path(__file__).resolve().parents[1]
INVENTORY_DIR = Path(__file__).resolve().parent / "inventory"
SERVERS_DIR = ROOT / "servers"


def normalize_json_text(text: str) -> str:
    return json.dumps(json.loads(text), indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def inventory_to_manifest(inv: dict) -> dict:
    manifest = {"binaries": [], "libs": [], "configs": []}
    for item in inv.get("devices", []):
        kind = item.get("type", "binary")
        section = {"binary": "binaries", "lib": "libs", "config": "configs"}.get(kind, "binaries")
        manifest[section].append({
            "repo": item["repo"],
            "version": item["version"],
            "asset": item["asset"],
            "extract": item.get("extract", ""),
            "path": item["path"],
        })
    return manifest


def clear_server_outputs(server_dir: Path, server_name: str):
    outputs = [
        server_dir / f"{server_name}.tar.gz",
        server_dir / "bom.json",
        server_dir / "build.log",
    ]
    for p in outputs:
        if p.exists():
            if p.suffix == ".gz":
                p.write_bytes(b"")
            else:
                p.write_text("", encoding="utf-8")

def main():
    if not INVENTORY_DIR.is_dir():
        print(f"[ERROR] dossier inventaire introuvable: {INVENTORY_DIR}")
        sys.exit(1)

    files = sorted(INVENTORY_DIR.glob("*.yml"))
    if not files:
        print("[INFO] aucun fichier d'inventaire trouvé.")
        return

    for inv_path in files:
        inv = yaml.safe_load(inv_path.read_text(encoding="utf-8"))
        server_name = inv.get("hostname", inv_path.stem)
        server_dir = SERVERS_DIR / server_name
        server_dir.mkdir(parents=True, exist_ok=True)

        manifest_path = server_dir / "manifest.json"
        new_manifest = inventory_to_manifest(inv)
        new_manifest_text = json.dumps(new_manifest, indent=2, ensure_ascii=False, sort_keys=True) + "\n"

        old_text = None
        if manifest_path.exists():
            old_text = normalize_json_text(manifest_path.read_text(encoding="utf-8"))

        if old_text == new_manifest_text:
            print(f"[OK] {server_name}: aucun changement")
            continue

        manifest_path.write_text(new_manifest_text, encoding="utf-8")
        clear_server_outputs(server_dir, server_name)

        print(f"[UPDATED] {server_name}: manifest modifié")
        print(f"           artefacts supprimés: {server_name}.tar.gz, bom.json, build.log")


if __name__ == "__main__":
    main()