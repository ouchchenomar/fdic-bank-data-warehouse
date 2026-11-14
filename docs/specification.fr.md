# Cahier des charges · Entrepôt de données bancaires FDIC

**Version 1.2 · 14 novembre 2026 · Auteur : Omar Ouchchen**

## 1. Contexte et objectif

Une équipe data reçoit les déclarations trimestrielles des banques américaines. Elle doit publier des chiffres fiables et pouvoir expliquer leur origine, leurs révisions et les incidents de chargement. Le projet reprend des pratiques de place de rapprochement, de migration et de traçabilité, inspirées de l'étude de cas publique HSBC / Google Cloud, dans un environnement local. [Étude de cas HSBC](https://cloud.google.com/customers/featured/hsbc)

**Utilisateur cible.** Un analyste crédit, un département risques ou un cabinet de conseil qui suit la santé des banques et les compare à leurs pairs. Le produit livré est un **suivi de santé et une comparaison entre pairs**, avec une page d'alerte précoce.

## 2. Sources réelles et périmètre

| Source | Données et grain | Usage |
|---|---|---|
| **FDIC BankFind · institutions** | Référentiel réel des établissements : identifiant FDIC CERT, nom, État du siège, statut publié | Dimension établissement |
| **FDIC BankFind · financials** | Déclarations réelles agrégées par établissement et date de clôture REPDTE. Clé `ID` = `CERT_REPDTE`. | Table de faits trimestrielle |
| **FDIC BankFind · history** | Événements de structure : changements de nom, fusions, agences | Historisation de la dimension |
| **FDIC BankFind · failures** | Faillites, avec date et coût | Page d'alerte précoce |
| **Téléchargements FDIC et FFIEC CDR** | Fichiers officiels, dont le Call Report complet du FFIEC | Échantillon reproductible et rapprochement REC-02 |

**Constats vérifiés le 12 novembre 2026, sans clé, HTTP 200 :**

- `financials` compte **4 411** déclarations au 31/12/2025 et **4 313** au 30/06/2026. Le 30/09/2026 n'est pas encore publié. Le T2 2026 a été indexé le 19/08/2026, environ 7 semaines après la clôture.
- `limit=10000` renvoie un trimestre entier en un appel.
- Chaque réponse expose `meta.index`, par exemple `risview_20260819185831`, qui identifie la version de la source.
- `history` répond, avec 14 133 événements pour Wells Fargo. `failures` recense 6 faillites en 2025-2026.

[Requête établissements](https://api.fdic.gov/banks/institutions?filters=CERT%3A3511&fields=CERT%2CNAME%2CSTALP%2CACTIVE&limit=1) · [Requête déclarations](https://api.fdic.gov/banks/financials?filters=CERT:3511&fields=CERT,REPDTE,ASSET,DEP,NETINC,EQ,LNLSNET,EQV,LNLSDEPR&sort_by=REPDTE&sort_order=DESC&limit=6) · [Requête faillites](https://api.fdic.gov/banks/failures?filters=FAILYR:%5B2025%20TO%202026%5D&fields=NAME,CERT,FAILDATE,COST) · [Documentation BankFind](https://api.fdic.gov/banks/docs/) · [Téléchargements FDIC](https://www.fdic.gov/bank-data-guide/data-downloads) · [Téléchargement en masse FFIEC](https://cdr.ffiec.gov/Public/PWS/DownloadBulkData.aspx)

**Périmètre de la V1.**

- Six trimestres, du **T1 2025 au T2 2026**, soit environ 26 000 déclarations.
- Le **T3 2026** est chargé en incrémental dès sa publication.
- La ventilation géographique utilise l'État du siège, issu d'un référentiel daté, avec la date de l'extraction affichée.
- La dimension établissement est historisée en V1 sur le nom, l'État et le statut actif.
- Les fusions complètes et les dépôts par agence (`sod`) sont réservés à une extension.

### 2.1 Contrat de données

Le contrat est versionné en YAML dans le dépôt. Il fixe pour chaque champ le type, l'unité, la nullabilité et la définition recopiée du dictionnaire FDIC.

| Règle | Contenu |
|---|---|
| Unités | Montants en **milliers de dollars**, ratios en **pourcentage**. Exemple : ASSET = 1 907 928 000 pour Wells Fargo au 30/06/2026, soit 1 908 milliards de dollars. |
| Cumul annuel | `NETINC` est un **cumul depuis le début de l'année**. Le flux d'un trimestre vaut le cumul du trimestre moins celui du trimestre précédent, sauf au T1. Même règle à confirmer pour `INTINC`. |
| Dates | `REPDTE` est au format `AAAAMMJJ`, `FAILDATE` au format `M/J/AAAA` et `ESTDATE` au format ISO. Tout est normalisé en date. |
| Clé | Couple `CERT` + `REPDTE` unique |
| Manquant | `NULL` et 0 restent distincts |
| Fraîcheur | Un trimestre est attendu environ 7 à 8 semaines après sa clôture |

### 2.2 Catalogue d'indicateurs

Les champs suivants ont été vérifiés le 12/11/2026 sur `financials`.

| Champ | Sens | Unité |
|---|---|---|
| ASSET, DEP, LNLSNET, EQ | Total des actifs, dépôts, prêts nets, fonds propres | milliers de $ |
| NETINC, INTINC | Résultat net, produits d'intérêts (cumul annuel) | milliers de $ |
| NCLNLS, RBCT1J | Prêts non performants, capital Tier 1 | milliers de $ |
| ROA, ROE, NIMY, EEFFR | Rentabilité des actifs et des fonds propres, marge nette d'intérêt, coefficient d'exploitation | % |
| EQV, LNLSDEPR, NCLNLSR, NTLNLSR, RBC1AAJ | Fonds propres / actifs, prêts / dépôts, taux de prêts non performants, pertes nettes sur prêts, ratio de levier Tier 1 | % |

## 3. Exigences fonctionnelles

| ID | Exigence |
|---|---|
| DWH-01 | Extraire les trimestres par pagination stable : pages de 1 000 lignes triées par `CERT`. Archiver chaque fichier brut avec date, URL, paramètres, nombre de lignes, empreinte et version de la source (`meta.index`). Vérifier la couverture du total annoncé. |
| DWH-02 | Normaliser identifiants, dates et montants selon le contrat de données. Contrôler l'unicité du couple CERT–REPDTE. Expliquer les lignes non appariées et conserver la distinction entre zéro et donnée manquante. |
| DWH-03 | Construire une dimension des établissements historisée (snapshot dbt, SCD2), une table des déclarations trimestrielles, un modèle de flux trimestriels pour les champs cumulés et une vue d'exploitation. Relier chaque valeur au lot dont elle provient. |
| DWH-04 | Détecter les révisions réelles. Chaque semaine, rejouer les quatre derniers trimestres et comparer une empreinte par ligne. Conserver la version précédente, le nouveau lot, la version de la source et la date d'observation du changement. Une correction injectée pour la recette est identifiée comme simulée. La fréquence observée des révisions fait partie du rapport. |
| DWH-05 | Publier une période uniquement après validation des volumes, du schéma, des clés et de la cohérence des ratios. La période est construite dans un schéma de lot, testée, puis rendue visible par bascule de la vue `published` dans une transaction. En cas d'échec, le dernier état publié est conservé et la relance part des données brutes. |
| DWH-06 | Afficher un tableau de bord : actifs, dépôts et indicateurs par trimestre, filtres par État et par taille, accès au détail d'un établissement jusqu'à son lot source. |
| DWH-07 | Recalculer les ratios publiés à partir de leurs composantes et les rapprocher avec une tolérance documentée. Vérifié le 12/11 pour Wells Fargo au 30/06/2026 : EQ / ASSET = 8,885 %, égal au `EQV` publié ; LNLSNET / DEP = 62,93 %, égal au `LNLSDEPR` publié. Les écarts figurent dans le rapport de lot. |
| DWH-08 | Page d'alerte précoce : croiser les faillites avec les indicateurs des trimestres précédents. Cas de référence : Community Bank and Trust – West Georgia (CERT 25796), en faillite le 01/05/2026, avec 17,3 % de prêts non performants, 1,3 % de fonds propres sur actifs et un ROA de −6,9 % au 31/03/2026. |

## 4. Exigences non fonctionnelles

| Thème | Exigence |
|---|---|
| Robustesse | Relance automatique avec attente croissante sur les réponses 429 et 5xx, puis échec propre du lot |
| Reproductibilité | Versions figées (Python, dbt, Airflow, PostgreSQL, images Docker). Mode hors ligne à partir d'un échantillon enregistré. |
| Traçabilité | Journaux structurés par lot. Aucun secret requis, l'API étant publique. |
| Performance | Durée d'un run complet mesurée et indiquée dans le README |

## 5. Architecture, outils et budget

**API et fichiers FDIC → ingestion Python → stockage brut local → PostgreSQL et dbt → Power BI.** Airflow orchestre les chargements et les relances par trimestre. Docker Compose démarre les services.

| Outil gratuit en local | Usage |
|---|---|
| **Python et PostgreSQL** | Extraction, registre de lots et entrepôt. [Python](https://docs.python.org/3/license.html) · [PostgreSQL](https://www.postgresql.org/about/licence/) |
| **dbt Core et dbt-postgres** | Transformations SQL, snapshots, contrôles, documentation et lignage. [dbt Core](https://github.com/dbt-labs/dbt-core) · [Adaptateur PostgreSQL](https://github.com/dbt-labs/dbt-adapters/tree/main/dbt-postgres) |
| **Apache Airflow** | Planification, historique et relance paramétrée. [Airflow](https://airflow.apache.org/) |
| **Power BI Desktop** | Tableau de bord et extraction détaillée (drillthrough). Le projet `.pbip` (modèle TMDL, rapport PBIR) est généré par script et versionné. |
| **Docker Compose** | Démarrage local reproductible |

**Exploitation.**

- Fournir un mode connecté et un mode hors ligne à partir d'un échantillon enregistré.
- Documenter les versions, la relance par période et la gestion des erreurs temporaires de l'API.
- Ne publier les données normalisées qu'après contrôle.
- Le rapport de lot affiche les lignes extraites, rejetées, rapprochées et publiées, ainsi que les écarts de ratios.
- **Ports :** configurables dans un fichier `.env` (PostgreSQL sur 5435 par défaut).
- **Commandes :** elles passent par `run.py`, sans dépendance à `make`.

**Qualité et intégration continue.**

- Tests `pytest` pour l'ingestion.
- Tests dbt : unicité, non-nullité, relations, plages de valeurs, tolérance des ratios, plus `dbt source freshness`.
- `pre-commit` en local.
- Workflow GitHub Actions versionné.

**Budget et délai.** 0 € de licence ou d'hébergement obligatoire, sur une machine existante. Estimation : 3 semaines à temps partiel.

## 6. Cahier de recette

| Test | Résultat exigé |
|---|---|
| REC-01 · Couverture | Les six trimestres sont chargés. Les écarts entre volumes bruts et publiés sont expliqués. |
| REC-02 · Rapprochement | Les montants de dix couples établissement–trimestre concordent avec la source officielle, à unité identique : les 5 plus grandes banques, 3 tirées au hasard, 1 avec une valeur à zéro et 1 banque défaillante. Tout écart reste visible dans le rapport. |
| REC-03 · Rejeu | Le même fichier ne crée ni ligne métier ni version supplémentaire. Le registre trace la tentative. |
| REC-04 · Révision | Une révision, réelle si elle a été observée, sinon simulée, génère une nouvelle version. Les deux valeurs et les deux lots restent consultables. |
| REC-05 · Source incomplète | Une page manquante ou un champ obligatoire supprimé interrompt la publication. Le dernier tableau de bord validé reste consultable. |
| REC-06 · Cohérence des ratios | Les ratios recalculés concordent avec les ratios publiés dans la tolérance documentée. Un écart injecté bloque la publication. |
| REC-07 · Flux trimestriel | Le résultat net du T2 2026 de Wells Fargo vaut 12 808 000 − 5 961 000 = 6 847 000 milliers de $. |
| REC-08 · Nouveau trimestre | Le T3 2026 se charge sans retraiter les trimestres déjà publiés, dès sa publication par la FDIC. |

## 7. Lots de livraison et livrables

1. **Lot 1** — contrat de données, échantillon hors ligne, ingestion paginée, registre de lots avec version de la source.
2. **Lot 2** — modèles dbt, snapshot de la dimension, flux trimestriels, rapprochement et cohérence des ratios, reprise et historisation des révisions.
3. **Lot 3** — orchestration Airflow, tableau de bord et page d'alerte précoce, guide d'exploitation, CI.

**Livrables du dépôt :**

- README en français et en anglais, avec un schéma d'architecture.
- Contrat de données.
- Décisions d'architecture (ADR) : idempotence des lots, versions des déclarations, publication par bascule, orchestration par Airflow.
- Documentation dbt et graphe de lignage, publiés sur GitHub Pages.
- Guide d'exploitation : relancer un trimestre, rejouer un lot, restaurer l'état publié.
- Procès-verbal de recette.

**Démonstrations attendues.**

- Remonter d'un chiffre du tableau de bord jusqu'à la publication FDIC et au lot qui l'a chargé.
- Montrer comment le système préserve le dernier résultat validé lors d'un échec.
- Montrer que les signaux de la page d'alerte précoce étaient visibles avant une faillite réelle.

## Historique des versions

| Version | Date | Changements |
|---|---|---|
| 1.0 | 11/11/2026 | Version initiale |
| 1.1 | 12/11/2026 | Périmètre étendu au T2 2026 et au T3 en incrémental. Ajout du contrat de données, du catalogue d'indicateurs, de DWH-07 (cohérence des ratios) et DWH-08 (alerte précoce), des exigences non fonctionnelles et de REC-06 à REC-08. Révisions réelles dans DWH-04, publication par bascule dans DWH-05, SCD2 en V1. Power BI remplace Metabase, Docker Compose remplace Podman. |
| 1.2 | 14/11/2026 | Version de livraison. Jalons exprimés en lots, livrables alignés sur le dépôt : projet Power BI `.pbip`, quatre ADR, procès-verbal de recette. |
