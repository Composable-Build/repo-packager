#!/usr/bin/env python3
import argparse
import json
import re
import subprocess
import sys
import tarfile
import urllib.request
import urllib.error
from datetime import datetime, timezone
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
    if re.match(r'^v?\d+\.\d+\.\d+$', spec):
        return spec

    tags = get_all_tags(repo, token)
    versioned = [(t, parse_semver(t)) for t in tags]
    versioned = [(t, v) for t, v in versioned if v is not None]
    versioned.sort(key=lambda x: x[1], reverse=True)

    if not versioned:
        die(f"aucune release trouvée pour {repo}")

    if spec == "*":
        return versioned[0][0]
    if spec.startswith("^"):
        base = parse_semver(spec[1:])
        candidates = [t for t, v in versioned if v.major == base.major and v >= base]
        if not candidates: die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]
    if spec.startswith("~"):
        base = parse_semver(spec[1:])
        candidates = [t for t, v in versioned if v.major == base.major and v.minor == base.minor and v >= base]
        if not candidates: die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]
    if spec.startswith(">="):
        base = parse_semver(spec[2:])
        candidates = [t for t, v in versioned if v >= base]
        if not candidates: die(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]

    die(f"specifier non supporté: {spec}")

def resolve_version_for_item(item: dict, trigger_repo: str, trigger_tag: str, token: str) -> str:
    repo = item["repo"]
    spec = item.get("version", "*")
    if repo == trigger_repo:
        trigger_v = parse_semver(trigger_tag)
        if spec == "*": return trigger_tag
        if re.match(r'^v?\d+\.\d+\.\d+$', spec):
            if trigger_tag != spec: die(f"{repo}: {trigger_tag} != {spec}")
            return trigger_tag
        if spec.startswith("^") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v < base:
                die(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith("~") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v.minor != base.minor or trigger_v < base:
                die(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith(">=") and trigger_v:
            base = parse_semver(spec[2:])
            if trigger_v < base: die(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
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

def get_release_asset_name(repo: str, tag: str, pattern: str, token: str) -> str:
    """Résout le vrai nom de l'asset via l'API GitHub en matchant un glob pattern."""
    import fnmatch
    data = github_get(
        f"https://api.github.com/repos/{ORG}/{repo}/releases/tags/{tag}", token
    )
    assets = [a["name"] for a in data.get("assets", [])]
    if not assets:
        die(f"aucun asset dans la release {repo}@{tag}")
    # pattern peut être "binary_two-*.tar.gz" ou un nom exact
    matches = [a for a in assets if fnmatch.fnmatch(a, pattern)]
    if not matches:
        die(f"aucun asset ne correspond à '{pattern}' dans {repo}@{tag}. Assets disponibles: {assets}")
    if len(matches) > 1:
        print(f"[WARN] plusieurs assets matchent '{pattern}': {matches} — on prend le premier")
    return matches[0]
    
def download_all_assets(manifest_path: Path, trigger_repo: str, trigger_tag: str, token: str) -> dict:
    """Télécharge tous les assets et retourne un dict repo -> tag résolu."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved = {}
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            repo = item.get("repo")
            if not repo:
                continue
            tag = resolve_version_for_item(item, trigger_repo, trigger_tag, token)
            resolved[repo] = tag
            pattern = item["asset"].replace("{tag}", tag)
            asset_name = get_release_asset_name(repo, tag, pattern, token)
            dest_dir = ROOT / "artifacts" / repo
            download_asset(repo, tag, asset_name, dest_dir, token)
    return resolved


def build_bill_of_materials(manifest_path: Path, resolved: dict, timestamp: str) -> dict:
    """Construit le récapitulatif des composants inclus."""
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    type_map = {"binaries": "binary", "libs": "lib", "configs": "config"}
    bom = {"built_at": timestamp, "components": []}
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            repo = item.get("repo")
            if not repo:
                continue
            bom["components"].append({
                "repo": repo,
                "type": type_map[section],
                "spec": item.get("version", "*"),
                "resolved": resolved.get(repo, "unknown"),
            })
    return bom


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--token", required=True)
    parser.add_argument("--build", required=False)
    args = parser.parse_args()

    # timestamp ISO 8601 UTC, ex: 20260523T212300Z
    now = datetime.now(timezone.utc)
    timestamp = now.strftime("%Y%m%dT%H%M%SZ")

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
        server_name = server_dir.name
        print(f"[INFO] rebuild {server_name}")

        # dossier du build : servers/<server>/<timestamp>/
        build_dir = server_dir / timestamp
        build_dir.mkdir(parents=True, exist_ok=True)

        # téléchargement + résolution des versions
        resolved = download_all_assets(manifest_path, args.repo, args.tag, args.token)

        # packaging
        log_lines = []
        proc = subprocess.run(
            [sys.executable, str(PACKAGER), str(manifest_path)],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        log_lines.append(proc.stdout)
        if proc.returncode != 0:
            log_lines.append(proc.stderr)
            (build_dir / "build.log").write_text("\n".join(log_lines), encoding="utf-8")
            die(f"packager échoué pour {server_name}")

        # sauvegarde du log
        (build_dir / "build.log").write_text(proc.stdout + proc.stderr, encoding="utf-8")

        # déplacement du package avec nom ISO 8601
        out = ROOT / "output" / "app.tar.gz"
        if not out.exists():
            die(f"package non généré pour {server_name}")

        package_name = f"{server_name}-{timestamp}.tar.gz"
        target = build_dir / package_name
        out.replace(target)
        print(f"[OK] {target}")

        # bill of materials (récapitulatif des composants inclus)
        bom = build_bill_of_materials(manifest_path, resolved, timestamp)
        bom_path = build_dir / "bom.json"
        bom_path.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        print(f"[BOM] {bom_path}")

        # affichage récap lisible
        print(f"\n{'─'*50}")
        print(f"  Package : {package_name}")
        print(f"  Serveur : {server_name}")
        print(f"  Date    : {now.strftime('%Y-%m-%d %H:%M:%S UTC')}")
        print(f"  Composants inclus :")
        for c in bom["components"]:
            print(f"    [{c['type']:8s}] {c['repo']:20s} {c['spec']:10s} → {c['resolved']}")
        print(f"{'─'*50}\n")

    # commit et push
    subprocess.run(["git", "config", "user.email", "ci@github-actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "add", "servers/"], cwd=str(ROOT), check=True)
    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(ROOT))
    if result.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"rebuild {args.repo}@{args.tag} [{timestamp}]"],
            cwd=str(ROOT), check=True
        )
        subprocess.run(["git", "push"], cwd=str(ROOT), check=True)
    else:
        print("[INFO] rien à committer")


if __name__ == "__main__":
    main()