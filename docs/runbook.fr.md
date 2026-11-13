# Guide d'exploitation

Ce guide dit quoi faire quand l'entrepôt tourne seul, et quand il s'arrête. Toutes les commandes se lancent depuis la racine du dépôt, avec le Python de l'environnement virtuel (`.venv/Scripts/python` sous Windows, `.venv/bin/python` ailleurs). Les choix d'orchestration sont expliqués dans l'[ADR 0004](adr/0004-airflow-orchestration-of-cli-commands.md).

## Composants

| Composant | Accès | Rôle |
|---|---|---|
| PostgreSQL 16 | `127.0.0.1:5435`, base `fdic_dwh` | Registre des lots (`ops`), données brutes (`raw`), marts dbt, vues publiées (`published`) |
| Airflow 3.3 | http://127.0.0.1:8096 (sans mot de passe, en local) | DAG `fdic_warehouse`, tous les jours à 07:00 UTC |
| Archive brute | `data/raw/<jeu>/<partition>/` | Un fichier JSON Lines et un manifeste par lot, avec leur SHA-256 |
| Power BI | `powerbi/FDIC.pbip` | Lit les vues `published` avec le compte `fdic_reader`, en lecture seule |

## Démarrer et arrêter

```bash
docker compose up -d                              # PostgreSQL seul
docker compose --profile airflow up -d airflow    # Airflow (base "airflow" créée au premier démarrage)
docker compose exec airflow airflow dags unpause fdic_warehouse   # le DAG est en pause à sa création
docker compose --profile airflow stop airflow     # arrêter Airflow, la base reste démarrée
```

Une fois sorti de pause, le DAG tourne chaque jour à 07:00 UTC, tant que le conteneur Airflow est démarré.

## Exécution normale

Le DAG enchaîne :

1. `migrate` : applique les migrations SQL (sans effet si elles le sont déjà) ;
2. `ingest_institutions`, `ingest_failures` : réextraient les deux référentiels ;
3. `plan_quarters` : calcule les trimestres à extraire, c'est-à-dire chaque trimestre terminé depuis le dernier chargé, et le lundi les quatre derniers trimestres chargés (fenêtre de révision) ;
4. `ingest_quarter` : une tâche par trimestre, nommée d'après lui (`2026Q3`) ;
5. `publish` : `dbt build`, puis publication si tous les tests passent ;
6. `report` et `check_freshness` : registre des lots, journal des publications, fraîcheur de la source.

Une exécution normale dure environ une minute (53 s le 13/11/2026, 75 s avec la fenêtre de révision). La plupart des jours, chaque extraction donne `duplicate`, puisque la source n'a pas changé. C'est attendu : rien n'est chargé, et la tentative reste dans le registre.

Pour voir l'état sans Airflow :

```bash
python run.py report --limit 20     # registre des lots, avec les erreurs
python run.py publications          # journal des publications, avec les tests en échec
```

## Procédures

### Relancer un trimestre

- **Dans Airflow** : ouvrir l'exécution, puis la tâche `ingest_quarter` et l'instance du trimestre (par exemple `2026Q2`), puis choisir *Clear* en gardant *Downstream* coché : `publish` et les tâches suivantes repartent avec elle.
- **Par un déclenchement** : *Trigger DAG* avec le paramètre `quarters` à `2026Q2`, ou une plage `2025Q1:2026Q2`. En ligne de commande :

  ```bash
  docker compose exec airflow airflow dags trigger fdic_warehouse --conf '{"quarters": "2026Q2"}'
  ```

- **À la main** : `python run.py ingest financials --quarters 2026Q2`, puis `python run.py publish`.

### Rejouer un lot

Rejouer un lot, c'est réextraire sa partition de la source. Deux résultats sont possibles :
- **`duplicate`** : le fichier a la même empreinte SHA-256 que le dernier lot chargé de la partition. Rien n'est chargé, aucune version n'est créée. C'est le cas normal (REC-03).
- **`loaded`** : la source a changé. Le nouveau lot devient la version courante, et l'ancienne reste dans `fct_filing_versions`. `rpt_filing_revisions` montre champ par champ ce qui a changé.

```bash
python run.py ingest financials --quarters 2026Q2   # un trimestre
python run.py ingest financials --last 4             # la fenêtre de révision
python run.py ingest institutions                    # un référentiel
```

L'archive de chaque lot (`data/raw/...`, manifeste compris) sert de preuve : elle donne l'URL, les paramètres, le total annoncé, la version de l'index FDIC et l'empreinte du fichier.

### Restaurer l'état publié

Si une publication pose problème une fois en ligne (chiffre contesté, régression vue dans le tableau de bord) :

```bash
python run.py publish --rollback    # les vues published repassent sur la publication précédente
python run.py publications          # la publication annulée est marquée rolled_back
```

Les trois dernières publications sont gardées. Le tableau de bord lit les vues : une actualisation suffit, rien à republier côté Power BI. La prochaine exécution du DAG publie de nouveau l'état courant. Mettez le DAG en pause tant que la cause n'est pas corrigée.

### Trimestre pas encore publié : tâche *skipped*

La FDIC publie un trimestre environ deux mois après sa fin. D'ici là, l'API annonce 0 ligne. La tâche `ingest_quarter` du trimestre sort avec le code 99 et Airflow la marque *skipped*. Le registre trace la tentative en `failed` avec le message « the source announces 0 rows for this partition (not published yet?) ». Il n'y a rien à faire, l'exécution du lendemain réessaie.

Il faut regarder de plus près si le trimestre est toujours absent plus de 75 jours après sa fin. Vérifiez alors sur https://api.fdic.gov/banks/financials?filters=REPDTE:20260930&limit=1 (remplacez la date).

### Extraction en échec

La tâche est rouge, et `publish` ne tourne pas (règle `none_failed`). Le tableau de bord garde donc la dernière publication.

1. `python run.py report --limit 10` donne l'erreur du lot :

   | Message | Cause | Action |
   |---|---|---|
   | `coverage: N rows extracted for M announced` | Source incomplète, ou pagination coupée | Relancer la tâche. Si l'erreur revient, comparer avec l'API à la main. |
   | `source index changed during pagination` | La FDIC a reconstruit son index pendant l'extraction | Relancer plus tard. |
   | `key field ... is empty`, `duplicate key`, `contract fields absent from every row`, `not a date in format ...` | La source ne respecte plus le contrat | Lire `ops.batch_reject` (ligne, champ, valeur). Si le changement est voulu par la FDIC, faire évoluer `contracts/fdic.yml` (nouvelle version) et l'expliquer dans un ADR. |
   | Erreurs HTTP 429 ou 5xx, délai dépassé | API indisponible | Le client a déjà réessayé avec attente croissante, et Airflow relance la tâche une fois, 15 minutes plus tard. Sinon, relancer à la main plus tard. |

2. Une fois la cause traitée, relancer la tâche (*Clear*, avec *Downstream*) : `publish` suit.

### Publication refusée

`publish` est rouge, et `run.py publications` donne `refused` avec les tests en échec. Les vues `published` n'ont pas bougé.

1. Lire les nœuds en échec dans `run.py publications`. Le détail est dans `dbt/logs/dbt.log` (dans le conteneur Airflow, `/opt/airflow/dbt/logs/dbt.log`).
2. Rejouer les tests seuls : `python run.py dbt build --select <modèle>+`.
3. Cas connu : un lot simulé (`simulate-revision`) a été chargé. Le test `assert_no_simulated_value_is_published` bloque. Réextraire le trimestre de la source (`python run.py ingest financials --quarters <trimestre>`), puis republier.
4. Le test `assert_qbp_reconciliation_within_tolerance` est un avertissement : il ne bloque pas, mais un écart au Quarterly Banking Profile doit être expliqué avant de diffuser.

### Alerte de fraîcheur

`check_freshness` est en avertissement après 2 jours sans extraction réussie (`loaded` ou `duplicate`), en échec après 8 jours. Toutes les tâches peuvent être vertes en apparence alors que le DAG ne tourne plus (pause, conteneur arrêté). Vérifier qu'Airflow tourne, que le DAG n'est pas en pause, puis lancer une exécution.

### Base de données indisponible

```bash
docker compose ps                      # état et santé du conteneur postgres
docker compose up -d postgres          # le redémarrer
docker compose logs --tail 50 postgres
```

Les données sont dans le volume Docker `pgdata` : redémarrer le conteneur ne perd rien. Après redémarrage, relancer l'exécution du jour.

### Actualiser le tableau de bord

1. Ouvrir `powerbi/FDIC.pbip` dans Power BI Desktop.
2. *Actualiser*. À la première connexion, choisir *Base de données*, utilisateur `fdic_reader`, mot de passe `FDIC_READER_PASSWORD` du fichier `.env`. La base locale n'a pas de TLS : accepter la connexion non chiffrée quand Power BI la propose.
3. Le compte `fdic_reader` ne lit que le schéma `published`. Un accès aux marts ou au registre est refusé.

Pour changer son mot de passe : modifier `FDIC_READER_PASSWORD` dans `.env`, lancer `python run.py db-init`, puis mettre à jour les identifiants dans Power BI (*Paramètres de la source de données*).

## Vérifications après incident

- `python run.py report --limit 10` : plus de lot `failed` autre qu'un trimestre non publié ;
- `python run.py publications --limit 3` : la dernière tentative est `published` ;
- `python run.py dbt source freshness` : `PASS` ;
- dans Power BI, page *Qualité et lignage* : la date d'actualisation et le dernier lot sont ceux attendus.

## Vérifier une modification avant de la livrer

```bash
python run.py check     # lint, tests, puis chargement hors ligne, build et publication dans une base jetable
```

La même commande tourne dans le workflow GitHub `ci`, déclenché à la main. `pre-commit install` ajoute le lint et le contrôle des fins de ligne avant chaque commit.
