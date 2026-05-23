# Pour lancer les tests

```bash
# depuis la racine de repo-packager
python3 -m pytest tests/test_rebuild_packages.py -v

# ou sans pytest
python3 tests/test_rebuild_packages.py
```


**Ce qui est couvert**

| Fonction                 | Cas testés                                               |
| ------------------------ | -------------------------------------------------------- |
| parse_semver             | avec/sans v, invalide                                    |
| resolve_tag              | *, ^, ~, >=, exact, pas de candidat, spec invalide       |
| resolve_version_for_item | trigger repo match/mismatch, délégation vers resolve_tag |
| manifest_uses_repo       | présent, absent, manifest vide                           |
| download_asset           | téléchargement + extraction, erreur HTTP 404             |

Aucun appel réseau réel : tout est mocké
