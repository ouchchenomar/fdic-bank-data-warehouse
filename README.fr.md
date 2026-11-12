# Entrepôt de données bancaires FDIC

*[English version](README.md)*

Ce projet charge dans un entrepôt PostgreSQL les déclarations trimestrielles d'environ 4 400 banques américaines, publiées par la FDIC. Chaque chiffre remonte jusqu'au fichier et au lot qui l'ont chargé. Rejouer un fichier ne duplique jamais les données. Un trimestre qui échoue à ses contrôles est refusé, et le dernier état validé reste intact.

**État au 12/11/2026 : la semaine 1 sur 3 est terminée.** L'ingestion, le registre de lots, le contrat de données, l'échantillon hors ligne et la couche de staging dbt avec ses contrôles tournent sur les données réelles. La [feuille de route](#feuille-de-route) donne la suite.

## Données chargées

| Jeu | Endpoint FDIC | Contenu au 12/11/2026 |
|---|---|---|
| Déclarations trimestrielles | `/financials` | 26 559 déclarations de 4 547 banques, du T1 2025 au T2 2026, 19 champs |
| Établissements | `/institutions` | 27 835 établissements, actifs ou non |
| Faillites | `/failures` | 4 117 faillites et opérations d'assistance depuis 1934 |

Le contrat de données ([contracts/fdic.yml](contracts/fdic.yml)) fixe pour chaque champ le type, l'unité, la nullabilité et le sens. Chaque champ a été vérifié sur l'API réelle.

## Fonctionnement

1. **Extraction.** Pages de 1 000 lignes, triées sur une clé stable. Relance avec attente croissante sur les erreurs 429, 5xx et réseau, en respectant `Retry-After`. Si la FDIC reconstruit son index pendant la pagination, le lot est refusé.
2. **Archivage.** Chaque lot écrit un fichier JSON Lines canonique (même contenu, mêmes octets) et un manifeste : URL, paramètres, total annoncé, version de la source et SHA-256.
3. **Contrôle.** Avant tout chargement, le lot est vérifié : champs du contrat, clés non vides et uniques, types et formats de date, total annoncé.
4. **Chargement.** Si l'empreinte du fichier est celle du dernier lot chargé, la tentative est tracée comme `duplicate` et rien n'est chargé. Sinon, les lignes sont copiées dans `raw.*` dans la même transaction que le statut `loaded`.
5. **Staging (dbt).** Typage, noms métier avec suffixe d'unité (`_kusd`, `_pct`) et tests.

Les choix de conception sont dans [docs/adr](docs/adr). Le cahier des charges complet est [docs/specification.fr.md](docs/specification.fr.md).

## Ce que les données réelles ont montré

Constats tirés des exécutions du 12/11/2026. Chacun est traité dans le code ou les tests.

- **Unités.** Les montants sont en milliers de dollars : l'`ASSET` de Wells Fargo, 1 907 928 000, vaut 1 908 milliards de dollars.
- **Résultat cumulé.** `NETINC` est cumulé depuis le 1er janvier. Le résultat du T2 2026 de Wells Fargo vaut 12 808 000 − 5 961 000 = 6 847 000 milliers de dollars, et non 12 808 000.
- **Les ratios publiés concordent avec leurs composantes.** 52 769 contrôles (EQ / ASSET contre `EQV`, LNLSNET / DEP contre `LNLSDEPR`), aucun écart supérieur à 0,01 point. La FDIC publie 0 quand les dépôts sont nuls : les 349 déclarations sans dépôts sont donc écartées du contrôle.
- **La clé des faillites a dû changer.** 488 faillites de 1934 à 1976 n'ont pas de CERT, et 44 CERT ont fait faillite deux fois. Le contrat a refusé le premier lot. La clé est désormais l'identifiant d'enregistrement FDIC (`ID`). Comme on ne peut ni le demander ni trier dessus, cette petite table est lue en une seule page.
- **Déclarants non appariés.** 57 banques (332 déclarations) sont dans `/financials` mais pas dans `/institutions`. Un avertissement dbt les signale tant que la cause n'est pas documentée.
- **Un trimestre non publié est refusé proprement.** Le T3 2026 renvoyait 0 ligne le 12/11/2026 : le lot est noté en échec et rien ne change en aval.
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
python run.py db-init                                       # schémas ops et raw
python run.py ingest financials --quarters 2025Q1:2026Q2    # un lot par trimestre
python run.py ingest institutions
python run.py ingest failures
python run.py report                                        # registre des lots
python run.py dbt build                                     # modèles de staging et tests
python -m pytest                                            # 39 tests
```

**Sans internet**, sur une base vide, on charge l'échantillon versionné. Il est construit sur 13 CERT : les cinq plus grandes banques, les six faillites de 2025-2026 et deux cas limites.

```bash
python run.py ingest all --quarters 2025Q1:2026Q2 --offline
```

## Feuille de route

- **Semaine 2 :**
  - historique des valeurs révisées (DWH-04) ;
  - dimension historisée (snapshot dbt, SCD2) ;
  - flux trimestriels pour les champs cumulés ;
  - marts ;
  - publication par bascule d'un schéma `published`, seulement après succès des tests (DWH-05).
- **Semaine 3 :**
  - DAG Airflow avec relance par trimestre ;
  - tableau de bord Power BI, avec une page d'alerte précoce construite sur les faillites ;
  - guide d'exploitation ;
  - CI ;
  - documentation dbt publiée sur GitHub Pages.

## Source des données

[API FDIC BankFind Suite](https://api.fdic.gov/banks/docs/). Données publiques de la Federal Deposit Insurance Corporation américaine, sans clé d'API. Le code est sous licence MIT, qui ne couvre pas les données.
