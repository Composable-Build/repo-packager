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
LOGS_DIR = ROOT / "logs"

ORG = "Composable-Build"

def die(msg, code=1):
    print(f"[ERROR] {msg}", file=sys.stderr)
    raise SystemExit(code)

class VersionMismatch(Exception):
    pass

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
        if not candidates:
            raise RuntimeError(f"aucune version satisfaisant {spec} pour {repo}")

        return candidates[0]
    if spec.startswith("~"):
        base = parse_semver(spec[1:])
        candidates = [t for t, v in versioned if v.major == base.major and v.minor == base.minor and v >= base]
        if not candidates:
            raise RuntimeError(f"aucune version satisfaisant {spec} pour {repo}")

        return candidates[0]
    if spec.startswith(">="):
        base = parse_semver(spec[2:])
        candidates = [t for t, v in versioned if v >= base]
        if not candidates:
            raise RuntimeError(f"aucune version satisfaisant {spec} pour {repo}")
        return candidates[0]

    raise RuntimeError(f"specifier non supporté: {spec}")


def resolve_version_for_item(item: dict, trigger_repo: str, trigger_tag: str, token: str) -> str:
    repo = item["repo"]
    spec = item.get("version", "*")
    if repo == trigger_repo:
        trigger_v = parse_semver(trigger_tag)
        if spec == "*":
            return trigger_tag
        if re.match(r'^v?\d+\.\d+\.\d+$', spec):
            if trigger_tag.lstrip("v") != spec.lstrip("v"):
                raise VersionMismatch(f"{repo}: {trigger_tag} != {spec}")
            return trigger_tag
        if spec.startswith("^") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v < base:
                raise VersionMismatch(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith("~") and trigger_v:
            base = parse_semver(spec[1:])
            if trigger_v.major != base.major or trigger_v.minor != base.minor or trigger_v < base:
                raise VersionMismatch(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
            return trigger_tag
        if spec.startswith(">=") and trigger_v:
            base = parse_semver(spec[2:])
            if trigger_v < base:
                raise VersionMismatch(f"{repo}: {trigger_tag} ne satisfait pas {spec}")
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
    import fnmatch
    data = github_get(f"https://api.github.com/repos/{ORG}/{repo}/releases/tags/{tag}", token)
    assets = [a["name"] for a in data.get("assets", [])]
    if not assets:
        raise RuntimeError(f"aucun asset dans la release {repo}@{tag}")
    matches = [a for a in assets if fnmatch.fnmatch(a, pattern)]
    if not matches:
        raise RuntimeError(f"aucun asset ne correspond à '{pattern}' dans {repo}@{tag}. Assets disponibles: {assets}")

    # recherche l'asset avec la plus grande version 
    def sort_key(name):
        m = re.search(r'(\d+\.\d+\.\d+\.\d+|\d+\.\d+\.\d+)', name)
        if m:
            return parse_semver(m.group(1)) or Version("0")
        return Version("0")

    matches.sort(key=sort_key)
    return matches[-1]  # dernier = version la plus haute

def validate_spec(repo: str, spec: str):
    if not VALID_SPECS.match(spec):
        raise RuntimeError(
            f"[CONFIG] spec invalide '{spec}' pour {repo}. "
            f"Formats acceptés : *, v1.2.3, ^v1.2.3, ~v1.2.3, >=v1.2.3"
        )

def download_all_assets(manifest_path: Path, trigger_repo: str, trigger_tag: str, token: str) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    resolved = {}
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            repo = item.get("repo")
            if not repo:
                continue
            spec = item.get("version", "*")
            validate_spec(repo, spec)
            tag = resolve_version_for_item(item, trigger_repo, trigger_tag, token)
            pattern = item["asset"].replace("{tag}", tag)
            asset_name = get_release_asset_name(repo, tag, pattern, token)
            resolved[repo] = {"tag": tag, "asset": asset_name}
            dest_dir = ROOT / "artifacts" / repo
            download_asset(repo, tag, asset_name, dest_dir, token)
    return resolved

def build_bill_of_materials(manifest_path: Path, resolved: dict) -> dict:
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    type_map = {"binaries": "binary", "libs": "lib", "configs": "config"}
    bom = {"components": []}
    for section in ("binaries", "libs", "configs"):
        for item in data.get(section, []):
            repo = item.get("repo")
            if not repo:
                continue
            
            asset = resolved.get(repo, {}).get("asset", "")
            m = re.search(r'(\d+\.\d+\.\d+\.\d+)', asset)
            full_version = m.group(1) if m else resolved.get(repo, {}).get("tag", "unknown")

            bom["components"].append({
                "repo": repo,
                "type": type_map[section],
                "spec": item.get("version", "*"),
                "resolved": resolved.get("tag", "unknown"),
                "build": full_version,
            })
    return bom

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--repo", required=True)
    parser.add_argument("--tag", required=True)
    parser.add_argument("--token", required=True)
    args = parser.parse_args()

    if not SERVERS_DIR.is_dir():
        die(f"dossier servers introuvable: {SERVERS_DIR}")
    
    LOGS_DIR.mkdir(parents=True, exist_ok=True)

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

        log_file = server_dir / "build.log"
        package_file = server_dir / f"{server_name}.tar.gz"
        bom_file = server_dir / "bom.json"
        error_log = LOGS_DIR / f"{server_name}-{args.repo}-{args.tag}.log"

        try:
            resolved = download_all_assets(manifest_path, args.repo, args.tag, args.token)

            proc = subprocess.run(
                [sys.executable, str(PACKAGER), str(manifest_path)],
                capture_output=True, text=True, cwd=str(ROOT),
            )
            log_file.write_text(proc.stdout + proc.stderr, encoding="utf-8")
            if proc.returncode != 0 or "[WARN]" in proc.stdout + proc.stderr:
                with log_file.open("a", encoding="utf-8") as f:
                    f.write(f"\n[ERROR] packager échoué pour {server_name}\n")
                raise RuntimeError(f"packager échoué pour {server_name}")

            out = ROOT / "output" / "app.tar.gz"
            if not out.exists():
`                raise RuntimeError(f"package non généré pour {server_name}")

            out.replace(package_file)
            print(f"[OK] {package_file}")

            bom = build_bill_of_materials(manifest_path, resolved)
            bom_file.write_text(json.dumps(bom, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
            log_file.write_text(proc.stdout + proc.stderr, encoding="utf-8")
            
            print(f"[BOM] {bom_file}")
            print(f"[LOG] {log_file}")

            print(f"\n{'─'*50}")
            print(f"  Package : {package_file.name}")
            print(f"  Serveur : {server_name}")
            print(f"  Composants inclus :")
            for c in bom["components"]:
                print(f"    [{c['type']:8s}] {c['repo']:20s} {c['spec']:10s} → {c['resolved']}")
            print(f"{'─'*50}\n")

        except VersionMismatch as e:
            print(f"[SKIP] {server_name}: {e}")
            continue  # pas de log, pas de touche aux fichiers existants
        except subprocess.CalledProcessError as e:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"\n[ERROR] {e}\n")
            print(f"[ERROR] {server_name}: packager a échoué (exit {e.returncode})", file=sys.stderr)
            log_file.rename(error_log)
        except Exception as e:
            with log_file.open("a", encoding="utf-8") as f:
                f.write(f"\n[ERROR] {e}\n")
            print(f"[ERROR] {server_name}: {e}", file=sys.stderr)
            log_file.rename(error_log)


    subprocess.run(["git", "config", "user.email", "ci@github-actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "config", "user.name", "GitHub Actions"], cwd=str(ROOT), check=True)
    subprocess.run(["git", "add", "servers/"], cwd=str(ROOT), check=True)

    result = subprocess.run(["git", "diff", "--cached", "--quiet"], cwd=str(ROOT))
    if result.returncode != 0:
        subprocess.run(
            ["git", "commit", "-m", f"rebuild {args.repo}@{args.tag}"],
            cwd=str(ROOT), check=True
        )
        subprocess.run(["git", "push"], cwd=str(ROOT), check=True)
    else:
        print("[INFO] rien à committer")

if __name__ == "__main__":
    main()