#!/usr/bin/env python3
import argparse
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SERVERS_DIR = ROOT / "servers"
PACKAGER = ROOT / "scripts" / "packager.py"

def die(msg, code=1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)

def manifest_uses_repo(manifest_path: Path, repo_name: str) -> bool:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            if repo_name in item.get("path", ""):
                return True
    return False

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    args = parser.parse_args()

    if not SERVERS_DIR.is_dir():
        die(f"dossier servers introuvable: {SERVERS_DIR}")

    manifests = sorted(SERVERS_DIR.glob("*/manifest.json"))
    if not manifests:
        die(f"aucun manifest trouvé dans {SERVERS_DIR}")

    matched = []
    for manifest_path in manifests:
        if manifest_uses_repo(manifest_path, args.repo):
            matched.append(manifest_path)

    if not matched:
        print(f"[INFO] aucun manifest ne référence {args.repo}")
        return

    for manifest_path in matched:
        server_dir = manifest_path.parent
        print(f"[INFO] rebuild {server_dir.name}")

        subprocess.run(
            [sys.executable, str(PACKAGER), str(manifest_path)],
            check=True,
            cwd=str(ROOT),
        )

        out = ROOT / "output" / "app.tar.gz"
        if not out.exists():
            die(f"package non généré pour {server_dir.name}")

        # nom explicite : <server>-<repo>-<tag>.tar.gz
        target = server_dir / f"{server_dir.name}-{args.repo}-{args.tag}.tar.gz"
        out.replace(target)
        print(f"[OK] {target}")

    # commit et push tout ce qui a changé dans servers/
    subprocess.run(["git", "config", "user.email", "ci@github-actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "add", "servers/"], cwd=str(ROOT), check=True)
    subprocess.run(
        ["git", "commit", "-m", f"rebuild packages for {args.repo}@{args.tag}"],
        cwd=str(ROOT), check=True
    )
    subprocess.run(["git", "push"], cwd=str(ROOT), check=True)

if __name__ == "__main__":
    main()