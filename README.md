# repo-packager

`repo-packager` assemble et publie les packages serveur à partir des releases GitHub.
Chaque serveur possède un manifest qui déclare ses dépendances avec des contraintes de version.
Le CI déclenche automatiquement le repackaging à chaque release.
Git est la source de vérité : le dernier build de chaque serveur est toujours dans `servers/<server>/`.

## Flux

1. Un tag est poussé sur un repo source (`repo-bin2`, `repo-lib2`, etc.).
2. Le workflow `build.yml` compile, teste et publie une release GitHub.
3. `notify-packager.yml` déclenche `rebuild-packages.yml` sur `repo-packager`.
4. `rebuild_packages.py` résout les versions, télécharge les assets et génère les packages.
5. Les packages sont committés dans `servers/`.

## Structure

```text
repo-packager/
  scripts/
    packager.py           — assemble app.tar.gz depuis les artifacts
    rebuild_packages.py   — résout, télécharge et package tous les serveurs concernés
  servers/
    <server>/
      manifest.json       — dépendances et contraintes de version
      <server>.tar.gz     — dernier package produit
      bom.json            — bill of materials du dernier build
      build.log           — log du dernier build réussi
  logs/
    <server>-<repo>-<tag>.log  — logs des builds en erreur
  artifacts/              — assets téléchargés temporairement
  output/                 — app.tar.gz intermédiaire produit par packager.py
  work/                   — arborescence temporaire de build
```

## Manifest

Chaque serveur déclare ses composants dans `servers/<server>/manifest.json` :

```json
{
  "binaries": [
    {
      "repo": "repo-bin2",
      "version": "^v1.0.0",
      "asset": "binary_two-*.tar.gz",
      "extract": "binary_two",
      "path": "artifacts/repo-bin2/binary_two"
    }
  ],
  "libs": [
    {
      "repo": "repo-lib2",
      "version": "^v1.0.0",
      "asset": "plugin_two-*.tar.gz",
      "extract": "plugin_two",
      "path": "artifacts/repo-lib2/plugin_two"
    }
  ],
  "configs": []
}
```

### Spécifiers de version

| Spécifier | Comportement |
|---|---|
| `*` | dernière release disponible |
| `v1.2.3` | version exacte |
| `^v1.2.0` | même major, >= base |
| `~v1.2.0` | même major + minor, >= base |
| `>=v1.2.0` | toute version >= base |

Si le tag déclenché ne satisfait pas le spécifier, le serveur est **skippé** (`[SKIP]`).

## Installation

```bash
pip install typer
```

## CLI

### list-servers

Liste tous les serveurs et leur état courant.

```bash
python cli.py list-servers
```

### status

Affiche le BOM et le package du dernier build d'un serveur.

```bash
python cli.py status <server>
```

### log

Affiche le log du dernier build réussi.

```bash
python cli.py log <server>
```

Affiche les logs d'erreur récents :

```bash
python cli.py log <server> --errors
```

### diff

Compare le `bom.json` courant avec un commit précédent.

```bash
python cli.py diff <server> <commit>
```

### package

Relance le packager localement pour un serveur.

```bash
python cli.py package <server>
python cli.py package <server> --with <commit>
python cli.py package <server> --dry-run
```

### deploy

Déploie le package courant d'un serveur.

```bash
python cli.py deploy <server>
python cli.py deploy <server> --dry-run
```

## Git et historique

Git conserve l'historique complet de chaque fichier. Pour retrouver l'état d'un serveur à un commit donné :

```bash
git log --follow -- servers/<server>/bom.json
git show <commit>:servers/<server>/bom.json
git diff <commit> -- servers/<server>/bom.json
```

## Notes

- Un build réussi écrase `<server>.tar.gz`, `bom.json` et `build.log` dans `servers/<server>/`.
- Un build en erreur place le log dans `logs/` sans toucher les fichiers existants du serveur.
- `packager.py` retourne `exit(1)` si un asset est manquant — aucun package partiel n'est généré.
- `rebuild_packages.py` continue sur les autres serveurs en cas d'échec sur l'un d'eux.