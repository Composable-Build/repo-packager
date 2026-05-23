#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
import urllib.error
from pathlib import Path

try:
    from packaging.version import Version
except ImportError:
    subprocess.run([sys.executable, "-m", "pip", "install", "packaging", "-q"], check=True)
    from packaging.version import Version

ROOT = Path(__file__).resolve().parents[1]
SERVERS_DIR = ROOT / "servers"
PACKAGER = ROOT / "scripts" / "packager.py"
ORG = "Composable-Build"


def die(msg, code=1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)


def parse_semver(tag: str):
    try:
        return Version(tag.lstrip("v"))
    except Exception:
        return None


def github_get(url: str, token: str):
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def get_all_tags(repo: str, token: str) -> list[str]:
    data = github_get(f"https://api.github.com/repos/{ORG}/{repo}/releases?per_page=100", token)
    return [r["tag_name"] for r in data]


def resolve_tag(repo: str, spec: str, token: str) -> str:
    # version exacte
    if re.match(r'^v?\d+\.\d+\.\d+$', spec):
        return spec

    tags = get_all_tags(repo, token)
    versioned = [(t, parse_semver(t)) for t in tags]
    versioned = [(t, v) for t, v in versioned if v is not None]
    versioned.sort(key=lambda x: x[1], reverse=True)

    if not versioned:
        die(f"aucune release trouvée pour {repo}")

    # *  → dernière release
    if spec == "*":
        return versioned[0][0]

    # ^v1.2.3 → même major, >= base
    if spec.startswith("^"):
        base = parse_semver(spec[1:])
        if base is None:
            die(f"specifier invalide: {spec}")
        candidates = [t for t, v in versioned if v.major == base.major and v >= base]
        if not candidates:
            die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]

    # ~v1.2.3 → même major+minor, >= base
    if spec.startswith("~"):
        base = parse_semver(spec[1:])
        if base is None:
            die(f"specifier invalide: {spec}")
        candidates = [t for t, v in versioned if v.major == base.major and v.minor == base.minor and v >= base]
        if not candidates:
            die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]

    # >=v1.2.0
    if spec.startswith(">="):
        base = parse_semver(spec[2:])
        if base is None:
            die(f"specifier invalide: {spec}")
        candidates = [t for t, v in versioned if v >= base]
        if not candidates:
            die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]

    die(f"specifier non supporté: {spec}")


def resolve_version_for_item(item: dict, trigger_repo: str, trigger_tag: str, token: str) -> str:
    repo = item["repo"]
    spec = item.get("version", "*")

    if repo == trigger_repo:
        # vérifie que le tag du déclencheur satisfait le specifier
        trigger_v = parse_semver(trigger_tag)
        if spec == "*":
            return trigger_tag
        if re.match(r'^v?\d+\.\d+\.\d+$', spec):
            if trigger_tag != spec:
                die(f"{repo}: tag {trigger_tag} ne correspond pas à la version exacte {spec}")
            return trigger_tag
        if spec.startswith("^") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v < base:
                die(f"{repo}: tag {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith("~") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v.minor != base.minor or trigger_v < base:
                die(f"{repo}: tag {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith(">=") and trigger_v:
            base = parse_semver(spec[2:])
            if trigger_v < base:
                die(f"{repo}: tag {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        return trigger_tag

    return resolve_tag(repo, spec, token)


def download_asset(repo: str, tag: str, asset_name: str, dest_dir: Path, token: str):
    dest_dir.mkdir(parents=True, exist_ok=True)
    url = f"https://github.com/{ORG}/{repo}/releases/download/{tag}/{asset_name}"
    dest_file = dest_dir / asset_name
    print(f"[DL] {url}")
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}",
        "Accept": "application/octet-stream",
    })
    try:
        with urllib.request.urlopen(req) as resp, open(dest_file, "wb") as f:
            f.write(resp.read())
    except urllib.error.HTTPError as e:
        die(f"téléchargement échoué ({e.code}): {url}")

    if asset_name.endswith(".tar.gz"):
        with tarfile.open(dest_file, "r:gz") as tf:
            tf.extractall(dest_dir)
        print(f"[DL] extrait dans {dest_dir}")


def manifest_uses_repo(manifest_path: Path, repo_name: str) -> bool:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            if item.get("repo") == repo_name:
                return True
    return False


def download_all_assets(manifest_path: Path, trigger_repo: str, trigger_tag: str, token: str):
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            repo = item.get("repo")
            if not repo:
                continue
            tag = resolve_version_for_item(item, trigger_repo, trigger_tag, token)
            asset_name = item["asset"].replace("{tag}", tag)
            dest_dir = ROOT / "artifacts" / repo
            download_asset(repo, tag, asset_name, dest_dir, token)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    if not SERVERS_DIR.is_dir():
        die(f"dossier servers introuvable: {SERVERS_DIR}")

    manifests = sorted(SERVERS_DIR.glob("*/manifest.json"))
    if not manifests:
        die(f"aucun manifest trouvé dans {SERVERS_DIR}")

    matched = [m for m in manifests if manifest_uses_repo(m, args.repo)]

    if not matched:
        print(f"[INFO] aucun manifest ne référence {args.repo}")
        return

    for manifest_path in matched:
        server_dir = manifest_path.parent
        print(f"[INFO] rebuild {server_dir.name}")

        download_all_assets(manifest_path, args.repo, args.tag, args.token)

        subprocess.run(
            [sys.executable, str(PACKAGER), str(manifest_path)],
            check=True,
            cwd=str(ROOT),
        )

        out = ROOT / "output" / "app.tar.gz"
        if not out.exists():
            die(f"package non généré pour {server_dir.name}")

        target = server_dir / f"{server_dir.name}-{args.repo}-{args.tag}.tar.gz"
        out.replace(target)
        print(f"[OK] {target}")

    # commit et push
    subprocess.run(["git", "config", "user.email", "ci@github-actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "add", "servers/"], cwd=str(ROOT), check=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "--quiet"],
        cwd=str(ROOT)
    )
    if result.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"rebuild packages for {args.repo}@{args.tag}"],
            cwd=str(ROOT), check=True
        )
        subprocess.run(["git", "push"], cwd=str(ROOT), check=True)
    else:
        print("[INFO] rien à committer")


if __name__ == "__main__":
    main()