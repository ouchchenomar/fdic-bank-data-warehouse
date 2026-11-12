# Entrepôt de données bancaires FDIC

*[English version](README.md)*

Ce projet charge dans un entrepôt PostgreSQL les déclarations trimestrielles d'environ 4 400 banques américaines, publiées par la FDIC. Chaque chiffre remonte jusqu'au fichier et au lot qui l'ont chargé. Rejouer un fichier ne duplique jamais les données. Une valeur révisée devient une nouvelle version sans effacer l'ancienne. Le tableau de bord ne lit que ce qui a passé tous les tests : un build en échec laisse intact le dernier état publié.

**État au 12/11/2026 : les semaines 1 et 2 sur 3 sont terminées.** La semaine 1 a livré l'ingestion, le registre de lots et le contrat de données. La semaine 2 a ajouté l'historique des versions, la dimension SCD2, les flux trimestriels, les marts et la publication contrôlée. Tout tourne sur les données réelles. Le scénario de recette est dans [docs/recette.fr.md](docs/recette.fr.md), et la [feuille de route](#feuille-de-route) donne la suite.

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
python run.py publish                                       # dbt build (67 tests), puis publication
python run.py publications                                  # journal des publications
python run.py ingest financials --last 4                    # réextraire la fenêtre de révision
python -m pytest                                            # 54 tests
```

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
dbt/models/marts/           faits, dimensions et rapports publiés
dbt/tests/                  cohérence des ratios, flux trimestriels, aucune valeur simulée publiée
data/sample/                échantillon hors ligne (versionné) ; data/raw/ n'est pas versionné
tests/                      tests unitaires, HTTP simulé et PostgreSQL
docs/                       cahier des charges, recette et décisions d'architecture
```

## Feuille de route

- **Semaine 3 :**
  - DAG Airflow avec relance par trimestre, et réextraction nocturne des quatre derniers trimestres ;
  - tableau de bord Power BI sur le schéma `published`, avec une page d'alerte précoce construite sur les faillites ;
  - rapprochement de dix couples banque–trimestre avec les Call Reports du FFIEC (REC-02) ;
  - chargement du T3 2026 dès sa publication par la FDIC (REC-08) ;
  - guide d'exploitation, CI, et documentation dbt publiée sur GitHub Pages.

## Source des données

[API FDIC BankFind Suite](https://api.fdic.gov/banks/docs/). Données publiques de la Federal Deposit Insurance Corporation américaine, sans clé d'API. Le code est sous licence MIT, qui ne couvre pas les données.
