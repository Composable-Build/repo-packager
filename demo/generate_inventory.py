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

TYPE_MAP = {
    "binary":   "binaries",
    "lib":      "libs",
    "config":   "configs",
    "firmware": "firmwares",
}

SUBDIR_MAP = {
    "binary":   "binaries",
    "lib":      "libs",
    "config":   "configs",
    "firmware": "firmwares",
}


def normalize(data: dict) -> str:
    return json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True) + "\n"


def build_asset_pattern(device: dict, inv: dict) -> str:
    name = device.get("extract", device["name"])
    dtype = device.get("type", "binary")
    if dtype == "firmware":
        mcu = device.get("mcu", "cortex-m4")
        return f"{name}-*-{mcu}.bin"
    os_ = inv.get("os", "linux")
    arch = inv.get("arch", "")
    return f"{name}-*-{os_}-{arch}.tar.gz"


def build_target(inv: dict) -> dict:
    return {
        "hostname": inv.get("hostname", ""),
        "cpu":      inv.get("cpu", ""),
        "arch":     inv.get("arch", ""),
        "os":       inv.get("os", ""),
        "libc":     inv.get("libc", ""),
        "endian":   inv.get("endian", "little"),
    }


def inventory_to_manifest(inv: dict) -> dict:
    manifest = {
        "target":    build_target(inv),
        "binaries":  [],
        "firmwares": [],
        "libs":      [],
        "configs":   [],
    }

    for device in inv.get("devices", []):
        dtype = device.get("type", "binary")
        section = TYPE_MAP.get(dtype, "binaries")
        subdir = SUBDIR_MAP.get(dtype, "binaries")

        entry = {
            "name":    device["name"],
            "repo":    device["repo"],
            "version": device["version"],
            "asset":   build_asset_pattern(device, inv),
            "path":    f"{subdir}/{device.get('extract', device['name'])}",
            "sha256":  "__computed_at_build__",
        }

        if dtype == "firmware":
            entry["transport"] = device.get("transport", "can")
            entry["can_id"]    = device.get("can_id", "")

        if "extract" in device and dtype != "firmware":
            entry["extract"] = device["extract"]

        manifest[section].append(entry)

    # configs : infos plateforme seulement (pas de sha256)
    manifest["configs"].append({
        k: inv.get(k, "")
        for k in ("cpu", "arch", "os", "libc", "endian")
    })

    return manifest


def clear_server_outputs(server_dir: Path, server_name: str):
    (server_dir / f"{server_name}.tar.gz").write_bytes(b"")
    (server_dir / "bom.json").write_text("", encoding="utf-8")
    (server_dir / "build.log").write_text("", encoding="utf-8")


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
        new_text = normalize(new_manifest)

        old_text = None
        if manifest_path.exists():
            try:
                old_text = normalize(json.loads(manifest_path.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                old_text = None

        if old_text == new_text:
            print(f"[--] {server_name}: aucun changement")
            continue

        manifest_path.write_text(new_text, encoding="utf-8")
        clear_server_outputs(server_dir, server_name)
        print(f"[UPDATED] {server_name}: manifest mis à jour → {manifest_path}")


if __name__ == "__main__":
    main()