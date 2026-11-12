# Recette · semaines 1 et 2

Exécutée le 12/11/2026 sur les données réelles de l'API FDIC, dans la base locale (PostgreSQL 16, Docker). Les critères REC-01 à REC-08 viennent du [cahier des charges](specification.fr.md).

## Synthèse

| Critère | Résultat | Preuve |
|---|---|---|
| REC-01 · Couverture | Validé | Six trimestres chargés, 26 559 déclarations publiées. Les écarts sont expliqués ci-dessous. |
| REC-02 · Rapprochement | Reporté en semaine 3 | Il faut les Call Reports du FFIEC pour dix couples banque–trimestre. |
| REC-03 · Rejeu | Validé | Quatre trimestres réextraits : quatre doublons tracés, aucune ligne ni version ajoutée. |
| REC-04 · Révision | Validé (simulée) | Aucune révision réelle observée. La révision simulée crée une version, et les deux valeurs et les deux lots restent consultables. |
| REC-05 · Source incomplète | Validé | Couvert par les tests automatisés, et sur données réelles par le T3 2026 vide, refusé. La publication en cours reste lue. |
| REC-06 · Cohérence des ratios | Validé | 52 769 contrôles sans écart. Un écart injecté bloque la publication. |
| REC-07 · Flux trimestriel | Validé | Wells Fargo, T2 2026 : 6 847 000 milliers de $ dans `published.fct_filings`. |
| REC-08 · Nouveau trimestre | En attente | Le T3 2026 renvoie encore 0 ligne. Le lot est refusé proprement. |

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

Tests automatisés (`python -m pytest`, 54 tests) :
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

## Hors ligne

Le même parcours tourne sans internet sur une base vide, à partir de l'échantillon versionné (14 CERT) : 8 lots chargés, 67 tests dbt réussis, puis publication.
