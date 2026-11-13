# Entrepôt de données bancaires FDIC

*[English version](README.md)*

Ce projet charge dans un entrepôt PostgreSQL les déclarations trimestrielles d'environ 4 400 banques américaines, publiées par la FDIC. Chaque chiffre remonte jusqu'au fichier et au lot qui l'ont chargé. Rejouer un fichier ne duplique jamais les données. Une valeur révisée devient une nouvelle version sans effacer l'ancienne. Le tableau de bord ne lit que ce qui a passé tous les tests : un build en échec laisse intact le dernier état publié.

**État au 13/11/2026 : les trois semaines prévues sont livrées.**
- Semaine 1 : ingestion, registre de lots et contrat de données.
- Semaine 2 : historique des versions, dimension SCD2, flux trimestriels, marts et publication contrôlée.
- Semaine 3 : orchestration Airflow, tableau de bord Power BI avec une page d'alerte précoce, rapprochement avec le Quarterly Banking Profile de la FDIC, guide d'exploitation et contrôles de CI.

Tout tourne sur les données réelles. Documentation :
- le scénario de recette : [docs/recette.fr.md](docs/recette.fr.md) ;
- le guide d'exploitation : [docs/runbook.fr.md](docs/runbook.fr.md) ;
- la **documentation dbt et le graphe de lignage** : [ouchchenomar.github.io/fdic-bank-data-warehouse/](https://ouchchenomar.github.io/fdic-bank-data-warehouse/).

Deux points dépendent d'événements extérieurs, voir [ce qui reste](#ce-qui-reste).

## Données chargées

| Jeu | Endpoint FDIC | Contenu au 12/11/2026 |
|---|---|---|
| Déclarations trimestrielles | `/financials` | 26 559 déclarations de 4 547 banques, du T1 2025 au T2 2026, 23 champs |
| Établissements | `/institutions` | 27 835 établissements, actifs ou non |
| Faillites | `/failures` | 4 117 faillites et opérations d'assistance depuis 1934 |

Le contrat de données ([contracts/fdic.yml](contracts/fdic.yml), version 2) fixe pour chaque champ le type, l'unité, la nullabilité et le sens. Chaque champ a été vérifié sur l'API réelle.

## Fonctionnement

1. **Extraction.** Pages de 1 000 lignes, triées sur une clé stable. Relance avec attente croissante sur les erreurs 429, 5xx et réseau, en respectant `Retry-After`. Si la FDIC reconstruit son index pendant la pagination, le lot est refusé.
2. **Archivage.** Chaque lot écrit un fichier JSON Lines canonique (même contenu, mêmes octets) et un manifeste : URL, paramètres, total annoncé, version de la source, version du contrat et SHA-256.
3. **Contrôle.** Avant tout chargement, le lot est vérifié : champs du contrat, clés non vides et uniques, types et formats de date, total annoncé.
4. **Chargement.** Si l'empreinte du fichier est celle du dernier lot chargé, la tentative est tracée comme `duplicate` et rien n'est chargé. Sinon, les lignes sont copiées dans `raw.*` dans la même transaction que le statut `loaded`.
5. **Staging (dbt).** Typage, noms métier avec suffixe d'unité (`_kusd`, `_pct`) et tests.
6. **Versions (DWH-04).** Chaque contenu distinct d'une déclaration est une version, avec la raison de son existence :
   - `initial` : premier chargement ;
   - `contract_change` : le contrat a ajouté des champs, aucune valeur n'a changé ;
   - `revision` : la FDIC a modifié une valeur ;
   - `simulated` et `restored_after_simulation` : une correction de test et son annulation.

   `rpt_filing_revisions` montre chaque champ modifié avec l'ancienne valeur, la nouvelle et l'écart.
7. **Marts.**
   - `fct_filings` contient la version courante de chaque déclaration, issue du dernier lot chargé de son trimestre. On y trouve les flux trimestriels tirés des montants cumulés, et le lignage de chaque ligne : lot, version de l'index FDIC et version du contrat.
   - `dim_institution` couvre tous les CERT, et `dim_institution_history` en garde l'historique SCD2, construit par un snapshot dbt.
   - `fct_failures` ajoute à chaque faillite la dernière déclaration de la banque avant sa chute.
8. **Publication contrôlée (DWH-05).** `run.py publish` lance `dbt build` :
   - si un test échoue, la tentative est tracée comme `refused` et les vues publiées ne changent pas ;
   - sinon, les marts sont copiés dans un nouveau schéma `pub_<horodatage>`, et les vues du schéma `published` basculent dessus dans une seule transaction ;
   - les trois dernières publications sont conservées, et `publish --rollback` revient à la précédente.
9. **Orchestration.** Le DAG Airflow `fdic_warehouse` tourne tous les jours à 07:00 UTC :
   - il extrait les établissements, les faillites, et chaque trimestre terminé depuis le dernier chargé, avec une tâche par trimestre ;
   - le lundi, il réextrait aussi les quatre derniers trimestres, pour capter les révisions ;
   - puis il publie.

   Un trimestre que la FDIC n'a pas encore publié finit en *skipped*, pas en échec. Chaque tâche lance une commande `run.py`, la même qu'à la main ([ADR 0004](docs/adr/0004-airflow-orchestration-of-cli-commands.md)).
10. **Tableau de bord.** Power BI lit les vues `published` avec le rôle `fdic_reader`, qui ne peut rien lire d'autre. Le script `powerbi/build_powerbi.py` génère le projet (`powerbi/FDIC.pbip` : un modèle TMDL et un rapport PBIR) à partir du schéma publié. Il a quatre pages :
    - vue d'ensemble, avec des filtres par État et par taille ;
    - fiche établissement, jusqu'au lot source de chaque chiffre ;
    - alerte précoce ;
    - qualité et lignage.

Les choix de conception sont dans [docs/adr](docs/adr). Le cahier des charges complet est [docs/specification.fr.md](docs/specification.fr.md).

## Ce que les données réelles ont montré

Constats tirés des exécutions du 12/11/2026. Chacun est traité dans le code ou les tests.

- **Unités.** Les montants sont en milliers de dollars : l'`ASSET` de Wells Fargo, 1 907 928 000, vaut 1 908 milliards de dollars.
- **Résultat cumulé.** `NETINC` est cumulé depuis le 1er janvier. Le résultat du T2 2026 de Wells Fargo vaut 12 808 000 − 5 961 000 = 6 847 000 milliers de dollars, et non 12 808 000. `fct_filings` calcule le flux du trimestre, et un test dbt vérifie que les flux d'une année ont pour somme son cumul.
- **Les ratios publiés concordent avec leurs composantes.** 52 769 contrôles comparent EQ / ASSET à `EQV` et LNLSNET / DEP à `LNLSDEPR`, sans aucun écart supérieur à 0,01 point. La FDIC publie 0 quand les dépôts sont nuls : les 349 déclarations sans dépôts sont donc écartées du contrôle. 340 d'entre elles viennent de sociétés fiduciaires (classe NC).
- **Les 57 déclarants absents de `/institutions` sont des sociétés fiduciaires.** 57 banques (332 déclarations) figurent dans `/financials` mais pas dans `/institutions`. Toutes ont la classe NC : ce sont surtout des trust companies non assurées, comme BlackRock Institutional Trust Company. La version 2 du contrat ajoute le nom, l'État, la ville et la classe déclarés avec chaque déclaration, et `dim_institution` les utilise pour ces 57 CERT.
- **Ajouter un champ n'est pas une révision.** Après le changement de contrat, les six trimestres ont été rechargés, et les 26 559 déclarations ont reçu une deuxième version. Elle est étiquetée `contract_change`, avec 0 valeur modifiée, car une version n'est comparée que sur les champs présents des deux côtés.
- **La clé des faillites a dû changer.** 488 faillites de 1934 à 1976 n'ont pas de CERT, et 44 CERT ont fait faillite deux fois. Le contrat a refusé le premier lot. La clé est désormais l'identifiant d'enregistrement FDIC (`ID`). Comme on ne peut ni le demander ni trier dessus, cette petite table est lue en une seule page.
- **Un trimestre non publié est refusé proprement.** Le T3 2026 renvoyait encore 0 ligne le 12/11/2026 : le lot est noté en échec et rien ne change en aval.
- **Aucune révision observée pour l'instant.** La réextraction des quatre derniers trimestres le 12/11/2026 a donné quatre doublons.
- **Formats de date différents.** `REPDTE` vaut `20260630` dans `/financials` et `06/30/2026` dans `/institutions`. `FAILDATE` vaut `5/1/2026`.

## Orchestration, sur données réelles

Exécution du 13/11/2026 (`airflow dags test fdic_warehouse`), 53 secondes du début à la fin :

```text
migrate                  success
ingest_institutions      success   [duplicate] 27 835 lignes, même fichier que le dernier lot : rien de chargé
ingest_failures          success   [duplicate] 4 117 lignes
plan_quarters            success   ["2026Q3"]
ingest_quarter[2026Q3]   skipped   the source announces 0 rows for this partition (not published yet?)
publish                  success   [published] pub_20261113T130802855z
report, check_freshness  success
```

Avec la fenêtre de révision (`--conf '{"revision_window": true}'`), l'exécution a pris 75 secondes :
- cinq tâches de trimestre ont tourné, de `2025Q3` à `2026Q3` ;
- les quatre trimestres publiés sont revenus en doublons : la FDIC n'a rien révisé cette semaine-là ;
- `2026Q3` a été marqué *skipped*.

## Alerte précoce, testée sur les faillites réelles

Chaque déclaration porte trois signaux (DWH-08). Les seuils sont des variables dbt indicatives, pas une notation prudentielle :
- **fonds propres** : ratio de levier Tier 1 sous 5 % ;
- **qualité des actifs** : prêts non performants au-dessus de 5 % des prêts ;
- **rentabilité** : ROA négatif.

`rpt_failure_signals` reprend toutes les déclarations d'une banque défaillante avant sa faillite. Cinq des six faillites de 2025-2026 ont au moins une déclaration dans l'entrepôt. La sixième, Pulaski Savings Bank, a fait faillite le 17/01/2025, avant le premier trimestre chargé.

| Banque (CERT) | Faillite | Signaux dans sa dernière déclaration | Première déclaration avec 2 signaux ou plus |
|---|---|---|---|
| Metropolitan Capital B&T (57488) | 30/01/2026 | 2 (T4 2025) | T1 2025, 4 trimestres avant |
| Community Bank and Trust – West Georgia (25796) | 01/05/2026 | 3 (T1 2026) | T2 2025, 4 trimestres avant |
| Kentland FS&LA (28722) | 10/07/2026 | 3 (T1 2026) | T1 2025, 5 trimestres avant |
| Small Business Bank (25744) | 17/07/2026 | 2 (T1 2026) | T1 2026, 1 trimestre avant |
| Santa Anna National Bank (5520) | 27/06/2025 | 0 (T1 2025) | aucune |

Quatre des cinq faillites portaient au moins deux signaux dans leur dernière déclaration. Community Bank and Trust est le cas de référence du cahier des charges. Au 31/03/2026, elle affiche :
- 17,3 % de prêts non performants ;
- des fonds propres à 1,3 % des actifs ;
- un ROA de −6,9 %.

Santa Anna National Bank montre la limite d'un filtre sur ratios : sa dernière déclaration paraissait saine. Au T2 2026, la liste de surveillance (`rpt_watchlist`) compte 25 banques avec au moins deux signaux. Trois portent les trois signaux, et sept en ont plus qu'au trimestre précédent.

## Rapprochement avec le Quarterly Banking Profile (REC-02)

Chaque trimestre, la FDIC publie les totaux du secteur dans son Quarterly Banking Profile (QBP). Le seed dbt `qbp_reference` reprend deux chiffres des communiqués QBP pour six trimestres, chacun avec son URL :
- le nombre d'établissements assurés ;
- le résultat net du trimestre.

`rpt_reconciliation_qbp` les compare aux déclarations publiées :

| Trimestre | Établissements assurés, QBP / entrepôt | Résultat net en Md$, QBP / entrepôt |
|---|---|---|
| T1 2025 | 4 462 / 4 462 | 70,6 / 70,41 (−0,27 %) |
| T2 2025 | 4 421 / 4 421 | 69,9 / 70,03 (+0,19 %) |
| T3 2025 | 4 379 / 4 379 | 79,3 / 79,32 |
| T4 2025 | 4 336 / 4 338 (+2) | 77,7 / 77,66 |
| T1 2026 | 4 278 / 4 279 (+1) | 80,5 / 80,45 |
| T2 2026 | 4 238 / 4 238 | 90,1 / 90,20 (+0,11 %) |

Les 12 contrôles sont dans la tolérance de 0,5 %, et 7 sont égaux à l'arrondi publié près. Les effectifs ne concordent qu'une fois deux classes écartées, car le QBP ne les compte pas parmi les établissements assurés :
- les sociétés fiduciaires non assurées (classe NC) ;
- les succursales américaines assurées de banques étrangères (classe OI).

Le cahier des charges demande aussi un rapprochement de dix couples banque–trimestre avec les Call Reports du FFIEC. Il reste ouvert : les sites du FFIEC ont répondu HTTP 403 depuis le réseau utilisé pour ce projet.

## Démarrage

Prérequis : Python 3.12 ou plus, Docker.

```bash
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements-dev.txt   # Linux/macOS : .venv/bin/python
cp .env.example .env            # puis définir POSTGRES_PASSWORD
docker compose up -d            # PostgreSQL 16 sur 127.0.0.1:5435
```

Ensuite, avec le Python de l'environnement virtuel :

```bash
python run.py db-init                                       # schémas ops et raw, journal des publications
python run.py ingest financials --quarters 2025Q1:2026Q2    # un lot par trimestre
python run.py ingest institutions
python run.py ingest failures
python run.py report                                        # registre des lots
python run.py publish                                       # dbt build (64 tests de données), puis publication
python run.py publications                                  # journal des publications
python run.py ingest financials --last 4                    # réextraire la fenêtre de révision
python -m pytest                                            # 64 tests
python run.py check                                         # lint, tests, parcours hors ligne complet (comme la CI)
```

**Airflow** (Airflow 3.3 sous Docker, sur http://127.0.0.1:8096) :

```bash
docker compose --profile airflow up -d airflow
docker compose exec airflow airflow dags unpause fdic_warehouse   # en pause à sa création
```

**Power BI** : `python powerbi/build_powerbi.py` écrit le projet. Ouvrir `powerbi/FDIC.pbip` dans Power BI Desktop et l'actualiser avec l'utilisateur `fdic_reader` et le mot de passe `FDIC_READER_PASSWORD` du fichier `.env`.

**Sans internet**, sur une base vide, on charge l'échantillon versionné, puis on publie. L'échantillon est construit sur 14 CERT :
- les cinq plus grandes banques ;
- les six faillites de 2025-2026 ;
- trois cas limites : dépôts nuls, prêts nuls, et une société fiduciaire absente de `/institutions`.

```bash
python run.py ingest all --quarters 2025Q1:2026Q2 --offline
python run.py publish
```

## Révision et contrôle de publication, sur données réelles

Exécution du 12/11/2026 (scénario complet dans [docs/recette.fr.md](docs/recette.fr.md)). Une correction simulée augmente de 10 % les fonds propres de Wells Fargo au T2 2026, sans toucher au ratio publié :

```text
$ python run.py simulate-revision --quarter 2026Q2 --cert 3511 --field EQ --change-pct 10
[loaded   ] financials_20260630_20261112T195337261Z  announced=4313 extracted=4313 rejected=0 loaded=4313

$ python run.py publish
[refused] pub_20261112T195338892z
            published views unchanged: pub_20261112T195245220z
            dbt build failed: assert_no_simulated_value_is_published (fail: Got 4313 results, [...]);
            assert_published_ratios_match_components (fail: Got 1 result, [...])

$ python run.py ingest financials --quarters 2026Q2        # même SHA-256 qu'avant la simulation
$ python run.py publish
[published] pub_20261112T195413659z
```

L'historique garde chaque étape :

```text
 version | change_kind               | batch_mode | field | previous  | new       | delta
---------+---------------------------+------------+-------+-----------+-----------+-----------
       1 | initial                   | api        |       |           |           |
       2 | contract_change           | api        |       |           |           |
       3 | simulated                 | simulated  | EQ    | 169518000 | 186469800 |  16951800
       4 | restored_after_simulation | api        | EQ    | 186469800 | 169518000 | -16951800
```

## Organisation du dépôt

```text
contracts/fdic.yml          contrat de données (champs, unités, clés, contrôles de ratios), version 2
sql/                        registre ops.batch, tables brutes, journal des publications
src/fdic_dwh/               client, sources, contrôles, pipeline, simulation, publication, CLI
dbt/models/staging/         vues typées sur les données brutes
dbt/models/intermediate/    versions des déclarations, derniers établissements
dbt/snapshots/              snapshot SCD2 des établissements
dbt/models/marts/           faits, dimensions, rapports d'alerte et de rapprochement publiés
dbt/seeds/                  chiffres de référence du Quarterly Banking Profile
dbt/tests/                  cohérence des ratios, flux trimestriels, aucune valeur simulée publiée
airflow/dags/               DAG fdic_warehouse
docker/airflow/             image Airflow, avec le projet dans son propre environnement virtuel
powerbi/                    projet Power BI (modèle TMDL, rapport PBIR) et le script qui le génère
data/sample/                échantillon hors ligne (versionné) ; data/raw/ n'est pas versionné
tests/                      tests unitaires, HTTP simulé et PostgreSQL
.github/workflows/ci.yml    le contrôle run.py check, lancé à la main
docs/                       cahier des charges, recette, guide d'exploitation et décisions d'architecture
```

## Ce qui reste

- **T3 2026 (REC-08).** L'exécution quotidienne chargera le trimestre dès que la FDIC le publiera. Rien n'est à changer.
- **Rapprochement par banque (REC-02).** Dix couples banque–trimestre restent à vérifier avec les Call Reports du FFIEC, depuis un réseau que le site du FFIEC accepte.
- **Captures du tableau de bord.** Captures d'écran, export PDF, et une vidéo de trois minutes sur la reprise d'un lot.

## Source des données

[API FDIC BankFind Suite](https://api.fdic.gov/banks/docs/). Données publiques de la Federal Deposit Insurance Corporation américaine, sans clé d'API. Les chiffres du rapprochement viennent des communiqués du Quarterly Banking Profile de la FDIC, listés avec leur URL dans [dbt/seeds/qbp_reference.csv](dbt/seeds/qbp_reference.csv). Le code est sous licence MIT, qui ne couvre pas les données.
