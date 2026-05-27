<br><br><br><br><br>
# Architecture CI/CD pour systèmes matériels modulaires
*Du build multi-cibles au provisionnement basé sur l'inventaire*
<br><br><br><br><br><br><br>
---

## Slide 1 : Introduction & Point de départ (L'expérience passée)
<br><br><br><br>
* Sébastien Galvagno – Ingénieur DevOps
* Approche technique basée sur l'expérience
* Cas d'usage : Chaîne de build multi-OS (GitHub Actions)
* Système adaptatif : 2 repos interconnectés

<br><br><br><br>
---
<br><br><br><br>
## Slide 2 : Généralisation du concept (La Notification)

* Architecture applicative distribuée (Multi-repos)
* Dépôts sources (Binaires, Librairies) ➔ Dépôt agrégateur (`repo-packager`)
* Mécanique : Release ➔ Notification ➔ Repackaging

<br><br><br><br>
---

## Slide 3 : Le Repackaging Multi-Cibles (L'adaptation au matériel)
<br><br><br><br>
* Objectif : S'adapter aux configurations matérielles (infrastructures, périphériques)
* Un orchestrateur, de multiples cibles
* Construction pilotée par des *Manifests* spécifiques

<br><br><br><br>
---

## Slide 4 : Démonstration - L'Orchestration en Action

![schema](orchestration.png)

---

## Slide 5 : L'Inventaire Matériel (La garantie du Manifest)

![schema](inventory.png)


