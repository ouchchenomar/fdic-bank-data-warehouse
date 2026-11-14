# Procès-verbal de recette

Exécutée du 12 au 14/11/2026 sur les données réelles de l'API FDIC, dans la base locale (PostgreSQL 16, Docker). Les critères REC-01 à REC-08 viennent du [cahier des charges](specification.fr.md).

## Synthèse

| Critère | Résultat | Preuve |
|---|---|---|
| REC-01 · Couverture | Validé | Six trimestres chargés, 26 559 déclarations publiées. Les écarts sont expliqués ci-dessous. |
| REC-02 · Rapprochement | Partiel | Au niveau du secteur, 12 contrôles sur 12 dans la tolérance face au Quarterly Banking Profile. Le rapprochement par banque avec les Call Reports du FFIEC reste ouvert : le site répond HTTP 403 depuis le réseau utilisé. |
| REC-03 · Rejeu | Validé | Quatre trimestres réextraits : quatre doublons tracés, aucune ligne ni version ajoutée. |
| REC-04 · Révision | Validé (simulée) | Aucune révision réelle observée. La révision simulée crée une version, et les deux valeurs et les deux lots restent consultables. |
| REC-05 · Source incomplète | Validé | Couvert par les tests automatisés, et sur données réelles par le T3 2026 vide. Le lot est refusé, et la publication en cours reste lue. |
| REC-06 · Cohérence des ratios | Validé | 52 769 contrôles sans écart. Un écart injecté bloque la publication. |
| REC-07 · Flux trimestriel | Validé | Wells Fargo, T2 2026 : 6 847 000 milliers de $ dans `published.fct_filings`. |
| REC-08 · Nouveau trimestre | En attente | Le T3 2026 renvoie encore 0 ligne le 14/11/2026. Le DAG le tente chaque jour et marque la tâche *skipped*. |

## REC-01 · Couverture

| Trimestre | Lignes annoncées | Lignes chargées |
|---|---|---|
| T1 2025 | 4 536 | 4 536 |
| T2 2025 | 4 494 | 4 494 |
| T3 2025 | 4 452 | 4 452 |
| T4 2025 | 4 411 | 4 411 |
| T1 2026 | 4 353 | 4 353 |
| T2 2026 | 4 313 | 4 313 |
| **Total** | **26 559** | **26 559** = lignes de `published.fct_filings` |

Écarts expliqués :
- **57 déclarants (332 déclarations) absents de `/institutions`.** Tous sont de classe NC (sociétés fiduciaires non assurées). Leurs attributs viennent de la déclaration elle-même (contrat v2), et `dim_institution` compte 27 835 + 57 = 27 892 lignes.
- **8 déclarations sans trimestre précédent** (banques créées en cours d'année). Leur flux trimestriel reste vide, avec `flow_basis = previous_quarter_missing`, au lieu d'un flux faux.

## REC-02 · Rapprochement

**Au niveau du secteur, validé.** Le seed `qbp_reference` reprend, pour six trimestres, le nombre d'établissements assurés et le résultat net trimestriel publiés dans les communiqués du Quarterly Banking Profile (QBP), chacun avec son URL. Le rapport `published.rpt_reconciliation_qbp` les compare aux déclarations publiées, avec l'écart, l'écart relatif et un statut. Le statut `match` veut dire égal à l'arrondi publié près, et `within_tolerance` un écart d'au plus 0,5 %.

| Trimestre | Établissements assurés, QBP / entrepôt | Statut | Résultat net en Md$, QBP / entrepôt | Écart | Statut |
|---|---|---|---|---|---|
| T1 2025 | 4 462 / 4 462 | match | 70,6 / 70,411 | −0,27 % | within_tolerance |
| T2 2025 | 4 421 / 4 421 | match | 69,9 / 70,033 | +0,19 % | within_tolerance |
| T3 2025 | 4 379 / 4 379 | match | 79,3 / 79,320 | +0,03 % | match |
| T4 2025 | 4 336 / 4 338 | within_tolerance | 77,7 / 77,661 | −0,05 % | match |
| T1 2026 | 4 278 / 4 279 | within_tolerance | 80,5 / 80,454 | −0,06 % | match |
| T2 2026 | 4 238 / 4 238 | match | 90,1 / 90,196 | +0,11 % | within_tolerance |

Pour que les effectifs concordent, deux classes sont écartées, car le QBP ne les compte pas comme établissements assurés : les sociétés fiduciaires non assurées (NC) et les succursales assurées de banques étrangères (OI). Le test dbt `assert_qbp_reconciliation_within_tolerance` signale tout statut `gap`. C'est un avertissement : il ne bloque pas la publication, mais l'écart reste visible sur la page *Qualité et lignage* du tableau de bord.

**Par banque, ouvert.** Le cahier des charges demande dix couples établissement–trimestre rapprochés avec les Call Reports du FFIEC : les 5 plus grandes banques, 3 au hasard, 1 avec une valeur nulle et 1 banque défaillante. Les sites `cdr.ffiec.gov` et `www.ffiec.gov` répondent HTTP 403 depuis le réseau utilisé pour ce projet (passerelle Azure Application Gateway), dans un navigateur comme en ligne de commande. Le générateur de fichiers de la FDIC repose sur la même API que l'ingestion : il ne constitue pas une source indépendante. Ce rapprochement reste à faire depuis un autre réseau.

## REC-03 · Rejeu

```text
$ python run.py ingest financials --last 4
[duplicate] financials_20250930_20261112T195304582Z  announced=4452 extracted=4452 rejected=0 loaded=0
            same file as financials_20250930_20261112T194212129Z: nothing loaded
[duplicate] financials_20251231_20261112T195313708Z  announced=4411 extracted=4411 rejected=0 loaded=0
[duplicate] financials_20260331_20261112T195319053Z  announced=4353 extracted=4353 rejected=0 loaded=0
[duplicate] financials_20260630_20261112T195322904Z  announced=4313 extracted=4313 rejected=0 loaded=0
```

Les tentatives restent dans le registre (`run.py report`). Aucune ligne n'est ajoutée dans `raw.fdic_financials`, et `fct_filing_versions` ne change pas.

## REC-04 et REC-06 · Révision simulée et contrôle de publication

**1. Publication de référence.** `python run.py publish` donne `[published] pub_20261112T195245220z`. Valeur publiée pour Wells Fargo (CERT 3511) au T2 2026 :

| equity_capital_kusd | equity_to_assets_pct | batch_mode |
|---|---|---|
| 169 518 000 | 8,8849 | api |

**2. Correction simulée.** Les fonds propres augmentent de 10 %, sans changer le ratio publié `EQV` :

```text
$ python run.py simulate-revision --quarter 2026Q2 --cert 3511 --field EQ --change-pct 10
[loaded   ] financials_20260630_20261112T195337261Z  announced=4313 extracted=4313 rejected=0 loaded=4313
```

**3. Publication refusée.** Deux tests échouent :
- le contrôle des ratios : EQ / ASSET ne correspond plus à `EQV`, et c'est l'écart injecté de REC-06 ;
- le garde-fou qui interdit de publier une valeur simulée.

```text
$ python run.py publish
[refused] pub_20261112T195338892z
            published views unchanged: pub_20261112T195245220z
            dbt build failed: assert_no_simulated_value_is_published (fail: Got 4313 results, configured to fail if != 0);
            assert_published_ratios_match_components (fail: Got 1 result, configured to fail if != 0)
```

Après le refus, `published.fct_filings` donne toujours 169 518 000. Seuls les marts internes (non publiés) montrent 186 469 800.

**4. Retour à la source.** Le trimestre est réextrait de l'API. Le nouveau lot a la même empreinte SHA-256 (`1104fcce55df…`) que l'extraction réelle d'avant la simulation.

```text
$ python run.py ingest financials --quarters 2026Q2
[loaded   ] financials_20260630_20261112T195405170Z  announced=4313 extracted=4313 rejected=0 loaded=4313
$ python run.py publish
[published] pub_20261112T195413659z
            published views now read pub_20261112T195413659z (previous: pub_20261112T195245220z)
```

**5. Historique consultable.** Dans `published.fct_filing_versions` et `published.rpt_filing_revisions` :

| Version | change_kind | Lot | Champ | Avant | Après | Écart |
|---|---|---|---|---|---|---|
| 1 | initial | financials_20260630_20261112T192217338Z | | | | |
| 2 | contract_change | financials_20260630_20261112T194225991Z | | | | |
| 3 | simulated | financials_20260630_20261112T195337261Z | EQ | 169 518 000 | 186 469 800 | +16 951 800 |
| 4 | restored_after_simulation | financials_20260630_20261112T195405170Z | EQ | 186 469 800 | 169 518 000 | −16 951 800 |

**6. Retour arrière.** `python run.py publish --rollback` fait pointer les vues sur `pub_20261112T195245220z`. Une nouvelle publication remet ensuite l'état courant. Le journal (`run.py publications`) garde les quatre tentatives : publiée, refusée, annulée (`rolled_back`), publiée.

## REC-05 · Source incomplète

Tests automatisés (`python -m pytest`, 64 tests) :
- `test_incomplete_source_is_refused_and_keeps_previous_state` : moins de lignes que le total annoncé → lot `failed`, rien n'est chargé ;
- `test_dropped_field_is_refused` : un champ du contrat absent de toutes les lignes → lot `failed` ;
- `test_failed_build_is_refused_and_published_views_stay` et `test_copy_error_is_refused_without_leftovers` : un build ou une copie en échec laisse les vues publiées sur la publication précédente.

Sur données réelles, le T3 2026 (0 ligne annoncée) donne un lot `failed` avec le message « the source announces 0 rows for this partition (not published yet?) ».

## REC-07 · Flux trimestriel

| Trimestre | net_income_ytd_kusd | net_income_qtr_kusd |
|---|---|---|
| T1 2026 | 5 961 000 | 5 961 000 |
| T2 2026 | 12 808 000 | **6 847 000** |

Le test `assert_quarterly_flows_add_up_to_ytd` vérifie, pour toutes les banques, que la somme des flux d'une année donne son cumul.

## REC-08 · Nouveau trimestre et orchestration

Le T3 2026 n'est pas encore publié par la FDIC : l'API annonce 0 ligne le 13/11/2026. Le DAG Airflow `fdic_warehouse` le traite ainsi :
- `plan_quarters` retient `["2026Q3"]`, seul trimestre terminé depuis le dernier chargé ;
- `ingest_quarter[2026Q3]` sort avec le code 99, et Airflow marque la tâche *skipped* ;
- `publish` tourne quand même (règle `none_failed`) et republie l'état courant ;
- le registre garde la tentative en `failed`, avec le message « the source announces 0 rows for this partition (not published yet?) ».

Exécutions du 13/11/2026 :

| Exécution | Durée | Tâches de trimestre | Résultat |
|---|---|---|---|
| Quotidienne | 53 s | `2026Q3` *skipped* | Référentiels en doublon, publication `pub_20261113T130802855z` |
| Avec fenêtre de révision | 75 s | `2025Q3` à `2026Q2` en doublon, `2026Q3` *skipped* | Aucune révision FDIC, publication réussie |

Le DAG tourne ensuite sur son planning. Les exécutions planifiées du 13/11 et du 14/11/2026 (07:00 UTC) ont réussi. Celle du 14/11, manquée pendant que la machine était éteinte, a été rattrapée au redémarrage.

Le chargement du T3 2026 lui-même reste à constater dès sa publication. Les trimestres déjà publiés ne sont pas retraités : `plan_quarters` ne retient que les trimestres terminés depuis le dernier chargé, sauf la fenêtre de révision du lundi.

## DWH-08 · Alerte précoce

Trois signaux par déclaration, avec des seuils indicatifs (variables dbt) : ratio de levier Tier 1 sous 5 %, prêts non performants au-dessus de 5 %, ROA négatif. Dernière déclaration avant faillite, dans `published.rpt_failure_signals` :

| Banque (CERT) | Faillite | Trimestre | Tier 1 | Prêts non performants | ROA | Signaux |
|---|---|---|---|---|---|---|
| Santa Anna National Bank (5520) | 27/06/2025 | T1 2025 | 8,62 % | 0,50 % | 1,73 % | 0 |
| Metropolitan Capital B&T (57488) | 30/01/2026 | T4 2025 | 1,83 % | 2,82 % | −6,92 % | 2 |
| Community Bank and Trust – West Georgia (25796) | 01/05/2026 | T1 2026 | 0,16 % | 17,28 % | −6,88 % | 3 |
| Kentland FS&LA (28722) | 10/07/2026 | T1 2026 | 1,66 % | 6,30 % | −4,77 % | 3 |
| Small Business Bank (25744) | 17/07/2026 | T1 2026 | 4,83 % | 4,81 % | −4,29 % | 2 |

Le cas de référence (CERT 25796, au 31/03/2026) est retrouvé : 17,3 % de prêts non performants, fonds propres à 1,3 % des actifs, ROA de −6,9 %. Pulaski Savings Bank, en faillite le 17/01/2025, n'a aucune déclaration chargée avant cette date. La liste de surveillance du T2 2026 compte 24 banques avec au moins deux signaux. Les signaux ne sont calculés que pour les établissements assurés (`is_insured_population`) : les classes OI et NC déclarent Tier 1, fonds propres et ROA à 0, ce qui donnait un faux signal de fonds propres pour Bank of China (relevé dans Power BI le 14/11/2026).

## Accès en lecture seule

Le rôle `fdic_reader`, utilisé par Power BI, lit les vues du schéma `published` (26 559 lignes dans `fct_filings`, 12 dans `rpt_reconciliation_qbp`). Une lecture de `marts.fct_filings` ou de `ops.batch` est refusée (`InsufficientPrivilege`). Les droits sont accordés par défaut sur les vues recréées à chaque publication : contrôlé après les publications du 13/11/2026.

## Hors ligne

Le même parcours tourne sans internet sur une base vide, à partir de l'échantillon versionné (14 CERT). `python run.py check` l'exécute dans une base jetable, après le lint et les tests : 8 lots chargés, 82 nœuds dbt réussis (dont 65 tests de données), 68 déclarations publiées, en 20 secondes au total.
