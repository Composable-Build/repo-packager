#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import typer

app = typer.Typer(no_args_is_help=True, add_completion=False)

ROOT = Path(__file__).resolve().parent
SERVERS = ROOT / "servers"
PACKAGER = ROOT / "scripts" / "packager.py"
LOGS = ROOT / "logs"


def get_server_dir(target: str) -> Path:
    path = SERVERS / target
    if not path.is_dir():
        raise typer.BadParameter(f"serveur inconnu: {path}")
    return path


def manifest_relpath(target: str) -> str:
    return f"servers/{target}/manifest.json"


def current_manifest_path(target: str) -> Path:
    path = SERVERS / target / "manifest.json"
    if not path.exists():
        raise typer.BadParameter(f"manifest introuvable: {path}")
    return path


def manifest_from_git(target: str, commit: str) -> Path:
    relpath = manifest_relpath(target)
    try:
        content = subprocess.check_output(
            ["git", "show", f"{commit}:{relpath}"],
            text=True, cwd=str(ROOT),
        )
    except subprocess.CalledProcessError as e:
        raise typer.BadParameter(f"impossible de lire {relpath} au commit {commit}") from e
    tmp = Path("/tmp") / f"{target}-{commit}-manifest.json"
    tmp.write_text(content)
    return tmp


@app.command()
def list_servers():
    """Liste tous les serveurs et leur état courant."""
    if not SERVERS.is_dir():
        typer.echo("Aucun serveur trouvé.")
        raise typer.Exit(1)
    servers = sorted([d for d in SERVERS.iterdir() if d.is_dir()])
    if not servers:
        typer.echo("Aucun serveur configuré.")
        raise typer.Exit()
    typer.echo(f"{'Serveur':<20} {'Package':<8} {'BOM':<6} {'Log':<6}")
    typer.echo("─" * 50)
    for s in servers:
        pkg = "✅" if (s / f"{s.name}.tar.gz").exists() else "❌"
        bom = "✅" if (s / "bom.json").exists() else "❌"
        log = "✅" if (s / "build.log").exists() else "  "
        typer.echo(f"{s.name:<20} {pkg:<8} {bom:<6} {log:<6}")


@app.command()
def status(target: str):
    """Affiche l'état courant d'un serveur (bom.json + manifest)."""
    server_dir = get_server_dir(target)

    bom_path = server_dir / "bom.json"
    pkg_path = server_dir / f"{target}.tar.gz"
    manifest_path = server_dir / "manifest.json"

    if not bom_path.exists():
        typer.echo(f"[{target}] aucun build disponible.")
        raise typer.Exit()

    bom = json.loads(bom_path.read_text(encoding="utf-8"))
    built_at = bom.get("built_at", "?")
    pkg_size = f"{pkg_path.stat().st_size // 1024}K" if pkg_path.exists() else "absent"

    typer.echo(f"\n{'─'*50}")
    typer.echo(f"  Serveur  : {target}")
    typer.echo(f"  Package  : {pkg_path.name} ({pkg_size})")
    typer.echo(f"  Composants :")
    for c in bom.get("components", []):
        typer.echo(f"    [{c['type']:8s}] {c['repo']:20s} {c['spec']:12s} → {c['resolved']}")

    if manifest_path.exists():
        typer.echo(f"\n  Manifest : {manifest_path}")
    typer.echo(f"{'─'*50}\n")


@app.command()
def log(
    target: str,
    errors: bool = typer.Option(False, "--errors", help="Affiche les logs d'erreur dans logs/"),
):
    """Affiche le build.log courant d'un serveur, ou les erreurs récentes."""
    if errors:
        if not LOGS.is_dir():
            typer.echo("Aucun log d'erreur.")
            raise typer.Exit()
        logs = sorted(LOGS.glob(f"{target}-*.log"))
        if not logs:
            typer.echo(f"Aucun log d'erreur pour {target}.")
            raise typer.Exit()
        for l in logs:
            typer.echo(f"\n=== {l.name} ===")
            typer.echo(l.read_text(encoding="utf-8"))
        raise typer.Exit()

    log_path = SERVERS / target / "build.log"
    if not log_path.exists():
        typer.echo(f"Aucun build.log pour {target}.")
        raise typer.Exit(1)
    typer.echo(log_path.read_text(encoding="utf-8"))

@app.command()
def history(
    target: str,
    file: str = typer.Option("bom.json", "--file", help="Fichier à suivre dans l'historique"),
):
    """Affiche l'historique Git d'un fichier serveur (bom.json par défaut)."""
    relpath = f"servers/{target}/{file}"
    subprocess.run(
        ["git", "log", "--oneline", "--follow", "--", relpath],
        cwd=str(ROOT), check=False,
    )


@app.command()
def diff(
    target: str,
    commit: str = typer.Argument(..., help="Commit Git à comparer avec l'état courant"),
    file: str = typer.Option("bom.json", "--file", help="Fichier à comparer"),
):
    """Compare un fichier serveur avec son état à un commit précédent."""
    relpath = f"servers/{target}/{file}"
    subprocess.run(
        ["git", "diff", commit, "--", relpath],
        cwd=str(ROOT), check=False,
    )



@app.command()
def package(
    target: str,
    with_: str | None = typer.Option(None, "--with", help="Commit Git du manifest à utiliser"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Lance le packager pour un serveur."""
    manifest_path = manifest_from_git(target, with_) if with_ else current_manifest_path(target)
    if dry_run:
        typer.echo(str(manifest_path))
        raise typer.Exit()
    result = subprocess.run([sys.executable, str(PACKAGER), str(manifest_path)], cwd=str(ROOT))
    raise typer.Exit(result.returncode)


@app.command()
def deploy(
    target: str,
    with_: str | None = typer.Option(None, "--with", help="Commit Git du manifest à utiliser"),
    dry_run: bool = typer.Option(False, "--dry-run"),
):
    """Déploie le package courant d'un serveur."""
    server_dir = get_server_dir(target)
    pkg_path = server_dir / f"{target}.tar.gz"

    if with_:
        manifest_path = manifest_from_git(target, with_)
        result = subprocess.run([sys.executable, str(PACKAGER), str(manifest_path)], cwd=str(ROOT))
        if result.returncode != 0:
            raise typer.Exit(result.returncode)

    if not pkg_path.exists():
        typer.echo(f"[ERROR] package absent: {pkg_path}")
        raise typer.Exit(1)

    if dry_run:
        typer.echo(f"deploy {pkg_path}")
        raise typer.Exit()

    # TODO: appel déploiement réel ici
    typer.echo(f"[OK] deployed {pkg_path.name}")


@app.command()
def show(
    target: str,
    commit: str = typer.Argument(..., help="Commit Git à lire"),
    file: str = typer.Option("bom.json", "--file", help="Fichier à lire"),
):
    """Affiche un fichier serveur tel qu'il était à un commit donné."""
    relpath = f"servers/{target}/{file}"
    subprocess.run(
        ["git", "show", f"{commit}:{relpath}"],
        cwd=str(ROOT), check=False,
    )

if __name__ == "__main__":
    app()