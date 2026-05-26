#!/usr/bin/env python3
"""
Lit les fichiers YAML d'inventaire dans demo/inventory/
et met à jour les manifest.json correspondants dans servers/.
"""
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

TYPE_MAP = {"binary": "binaries", "lib": "libs", "config": "configs"}


def inventory_to_manifest(inv: dict) -> dict:
    manifest = {"binaries": [], "libs": [], "configs": []}
    for device in inv.get("devices", []):
        section = TYPE_MAP.get(device.get("type", "binary"), "binaries")
        manifest[section].append({
            "repo":    device["repo"],
            "version": device["version"],
            "asset":   device["asset"],
            "extract": device.get("extract", ""),
            "path":    device["path"],
        })
    return manifest


def main():
    if not INVENTORY_DIR.is_dir():
        print(f"[ERROR] dossier inventaire introuvable: {INVENTORY_DIR}")
        sys.exit(1)

    files = sorted(INVENTORY_DIR.glob("*.yml"))
    if not files:
        print("[INFO] aucun fichier d'inventaire trouvé.")
        sys.exit(0)

    for inv_path in files:
        inv = yaml.safe_load(inv_path.read_text(encoding="utf-8"))
        hostname = inv.get("hostname", inv_path.stem)
        server_dir = SERVERS_DIR / hostname
        server_dir.mkdir(parents=True, exist_ok=True)

        manifest = inventory_to_manifest(inv)
        manifest_path = server_dir / "manifest.json"
        manifest_path.write_text(
            json.dumps(manifest, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8"
        )
        print(f"[OK] {hostname} → {manifest_path}")
        print(f"     cpu: {inv.get('cpu', '?')}  arch: {inv.get('arch', '?')}")
        for d in inv.get("devices", []):
            print(f"     [{d.get('type','binary'):8s}] {d['repo']:20s} {d['version']}")
        print()


if __name__ == "__main__":
    main()