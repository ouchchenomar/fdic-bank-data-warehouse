"""Generate the Power BI project (PBIP: TMDL model + PBIR report) on the published views.

    python powerbi/build_powerbi.py

The columns are read from information_schema, so the model follows the marts. The project
holds connection metadata only: no credential and no data. Power BI Desktop asks for the
login on the first refresh: fdic_reader, password FDIC_READER_PASSWORD from .env.
Adapted from the generator of the author's Parcours platform.
"""

from __future__ import annotations

import json
import shutil
import sys
import uuid
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdic_dwh.config import load_settings  # noqa: E402
from fdic_dwh.db import connect  # noqa: E402

BI = ROOT / "powerbi"
MODEL = BI / "FDIC.SemanticModel"
REPORT = BI / "FDIC.Report"
NAMESPACE = uuid.UUID("5b3f0c1e-2f8a-4d36-9a57-0c6f3e8d1b42")
SERVER, DATABASE, SCHEMA = "127.0.0.1:5435", "fdic_dwh", "published"

TABLES = [
    "dim_institution",
    "fct_filings",
    "fct_filing_versions",
    "rpt_filing_revisions",
    "fct_failures",
    "rpt_failure_signals",
    "rpt_watchlist",
    "rpt_reconciliation_qbp",
    "rpt_batches",
]
HIDDEN = {
    "filing_id", "filing_version_id", "revision_id", "reconciliation_id", "failure_signal_id",
    "row_hash", "asset_size_order", "file_sha256", "source_index_created_at",
}
SORT_BY = {
    ("fct_filings", "report_quarter_label"): "report_date",
    ("fct_filings", "asset_size_group"): "asset_size_order",
    ("rpt_failure_signals", "report_quarter_label"): "report_date",
    ("rpt_reconciliation_qbp", "report_quarter_label"): "report_date",
}
RELATIONSHIPS = [
    ("fct_filings", "cert", "dim_institution", "cert"),
    ("fct_failures", "cert", "dim_institution", "cert"),
    ("fct_filing_versions", "filing_id", "fct_filings", "filing_id"),
    ("rpt_filing_revisions", "filing_id", "fct_filings", "filing_id"),
]
TYPES = {
    "integer": "int64",
    "smallint": "int64",
    "bigint": "int64",
    "numeric": "double",
    "double precision": "double",
    "boolean": "boolean",
    "date": "dateTime",
    "timestamp with time zone": "dateTime",
    "timestamp without time zone": "dateTime",
    "text": "string",
    "character varying": "string",
}

# Stocks are read at the last quarter in the filter context: summing assets over several
# quarters would mean nothing. DAX only aggregates what dbt has already computed.
IN_LAST_QUARTER = "fct_filings[report_date] = d"


def at_last_quarter(aggregate: str, divisor: str | None = None) -> str:
    """aggregate (optionally divided) at the last quarter of the filter context."""
    value = f"CALCULATE({aggregate}, {IN_LAST_QUARTER})"
    body = f"DIVIDE({value}, {divisor})" if divisor else value
    return f"VAR d = MAX(fct_filings[report_date]) RETURN {body}"


MEASURES = [
    ("Banques", at_last_quarter("DISTINCTCOUNT(fct_filings[cert])"),
     "#,0", "Bilan", "Banques déclarantes au dernier trimestre du contexte."),
    ("ActifsMd", at_last_quarter("SUM(fct_filings[total_assets_kusd])", "1000000"),
     "#,0.0", "Bilan",
     "Total des actifs, en milliards de dollars, au dernier trimestre du contexte."),
    ("DepotsMd", at_last_quarter("SUM(fct_filings[total_deposits_kusd])", "1000000"),
     "#,0.0", "Bilan", "Total des dépôts, en milliards de dollars."),
    ("ResultatTrimestreMd", at_last_quarter("SUM(fct_filings[net_income_qtr_kusd])", "1000000"),
     "#,0.00", "Bilan", "Résultat net du trimestre seul (flux), en milliards de dollars."),
    ("FondsPropresSurActifs", at_last_quarter(
        "SUM(fct_filings[equity_capital_kusd])",
        f"CALCULATE(SUM(fct_filings[total_assets_kusd]), {IN_LAST_QUARTER})"),
     "0.00%", "Bilan", "Fonds propres / actifs, agrégé (somme sur somme)."),
    ("ROAPublie", at_last_quarter("AVERAGE(fct_filings[roa_pct])", "100"),
     "0.00%", "Bilan", "ROA publié par la FDIC ; moyenne simple si plusieurs banques."),
    ("PretsNonPerformants",
     at_last_quarter("AVERAGE(fct_filings[noncurrent_loans_ratio_pct])", "100"),
     "0.00%", "Bilan",
     "Taux de prêts non performants publié ; moyenne simple si plusieurs banques."),
    ("DonneesAu", '"Données au " & FORMAT(MAX(fct_filings[report_date]), "dd/MM/yyyy")',
     "", "Bilan", "Dernier trimestre du contexte."),
    ("FaillitesCouvertes", "COALESCE(DISTINCTCOUNT(rpt_failure_signals[failure_id]), 0)",
     "0", "Alerte précoce", "Faillites dont au moins une déclaration est dans l'entrepôt."),
    ("FaillitesSignalees",
     "COALESCE(CALCULATE(DISTINCTCOUNT(rpt_failure_signals[failure_id]), "
     "rpt_failure_signals[quarters_before_failure] = 1, "
     "rpt_failure_signals[signal_count] >= 2), 0)",
     "0", "Alerte précoce", "Faillites avec au moins deux signaux dans la dernière déclaration."),
    ("ListeSurveillance", "COALESCE(COUNTROWS(rpt_watchlist), 0)",
     "0", "Alerte précoce", "Banques du dernier trimestre avec au moins deux signaux."),
    ("TroisSignaux",
     "COALESCE(CALCULATE(COUNTROWS(rpt_watchlist), rpt_watchlist[signal_count] = 3), 0)",
     "0", "Alerte précoce", "Banques du dernier trimestre avec les trois signaux."),
    ("LotsCharges",
     'COALESCE(CALCULATE(COUNTROWS(rpt_batches), rpt_batches[status] = "loaded"), 0)',
     "0", "Qualité", "Lots chargés."),
    ("LotsDoublons",
     'COALESCE(CALCULATE(COUNTROWS(rpt_batches), rpt_batches[status] = "duplicate"), 0)',
     "0", "Qualité", "Rejeux identiques au dernier lot chargé : tracés, rien de chargé."),
    ("LotsEchecs",
     'COALESCE(CALCULATE(COUNTROWS(rpt_batches), rpt_batches[status] = "failed"), 0)',
     "0", "Qualité", "Lots refusés (contrat, couverture, trimestre non publié)."),
    ("Rapprochements",
     'FORMAT(COALESCE(CALCULATE(COUNTROWS(rpt_reconciliation_qbp), '
     'rpt_reconciliation_qbp[status] IN {"match", "within_tolerance"}), 0), "0") & " / " & '
     'FORMAT(COALESCE(COUNTROWS(rpt_reconciliation_qbp), 0), "0")',
     "", "Qualité", "Contrôles QBP conformes (égaux ou dans la tolérance) sur le total."),
    ("ActualiseLe",
     '"Actualisé le " & FORMAT(MAX(Actualisation[actualise_le]), "dd/MM/yyyy HH:mm") & " UTC"',
     "", "Qualité", "Heure de la dernière actualisation du modèle."),
]


def tag(name: str) -> str:
    return str(uuid.uuid5(NAMESPACE, name))


def write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8", newline="\n")


def save(path: Path, value: dict) -> None:
    write(path, json.dumps(value, ensure_ascii=False, indent=2) + "\n")


def read_schema() -> dict[str, list[tuple[str, str]]]:
    with connect(load_settings().conninfo) as conn:
        rows = conn.execute(
            "select table_name, column_name, data_type from information_schema.columns"
            " where table_schema = %s and table_name = any(%s)"
            " order by table_name, ordinal_position",
            (SCHEMA, TABLES),
        ).fetchall()
    schema: dict[str, list[tuple[str, str]]] = {}
    for table, column, data_type in rows:
        schema.setdefault(table, []).append((column, data_type))
    missing = set(TABLES) - set(schema)
    if missing:
        raise SystemExit(f"not in {SCHEMA}: {sorted(missing)}. Run run.py publish first.")
    return schema


def column_format(name: str, data_type: str) -> str | None:
    if data_type == "date":
        return "dd/MM/yyyy"
    if data_type.startswith("timestamp"):
        return "dd/MM/yyyy HH:mm"
    if name.endswith("_kusd"):
        return "#,0"
    if name.endswith("_pct"):
        return "0.00"
    if name == "relative_gap":
        return "0.00%"
    if TYPES[data_type] == "double":
        return "#,0.###"
    if TYPES[data_type] == "int64":
        return "0"
    return None


def build_model(schema: dict[str, list[tuple[str, str]]]) -> None:
    definition = MODEL / "definition"
    shutil.rmtree(definition, ignore_errors=True)
    write(definition / "database.tmdl", "database FDIC\n\tcompatibilityLevel: 1550\n")
    write(definition / "model.tmdl", "\n".join([
        "model Model",
        "\tculture: fr-FR",
        "\tdefaultPowerBIDataSourceVersion: powerBI_V3",
        "\tsourceQueryCulture: fr-FR",
        "\tdataAccessOptions",
        "\t\tlegacyRedirects",
        "\t\treturnErrorValuesAsNull",
        "",
        '\tannotation PBI_ProTooling = ["DevMode"]',
        "\tannotation __PBI_TimeIntelligenceEnabled = 0",
        "",
        *[f"ref table {name}" for name in [*TABLES, "Mesures", "Actualisation"]],
        "",
    ]))
    write(definition / "expressions.tmdl", "\n".join([
        f'expression ServeurPostgreSQL = "{SERVER}" meta [IsParameterQuery=true, Type="Text", '
        "IsParameterQueryRequired=true]",
        "\tlineageTag: " + tag("server"),
        "",
        f'expression BasePostgreSQL = "{DATABASE}" meta [IsParameterQuery=true, Type="Text", '
        "IsParameterQueryRequired=true]",
        "\tlineageTag: " + tag("database"),
        "",
    ]))
    for table in TABLES:
        lines = [f"table {table}", "\tlineageTag: " + tag(table)]
        timestamps = []
        for column, data_type in schema[table]:
            lines += [
                "",
                f"\tcolumn {column}",
                f"\t\tdataType: {TYPES[data_type]}",
                "\t\tlineageTag: " + tag(f"{table}.{column}"),
                "\t\tsummarizeBy: none",
                f"\t\tsourceColumn: {column}",
            ]
            if column in HIDDEN:
                lines.append("\t\tisHidden")
            fmt = column_format(column, data_type)
            if fmt:
                lines.append(f"\t\tformatString: {fmt}")
            if (table, column) in SORT_BY:
                lines.append(f"\t\tsortByColumn: {SORT_BY[(table, column)]}")
            if data_type == "date":
                lines += ["", "\t\tannotation UnderlyingDateTimeDataType = Date"]
            if data_type == "timestamp with time zone":
                timestamps.append(column)
        source = f'Source{{[Schema="{SCHEMA}", Item="{table}"]}}[Data]'
        steps = [
            "\t\t\t\tlet",
            "\t\t\t\t    Base = PostgreSQL.Database(ServeurPostgreSQL, BasePostgreSQL),",
            f"\t\t\t\t    Donnees = {source.replace('Source', 'Base', 1)}"
            + ("," if timestamps else ""),
        ]
        result = "Donnees"
        if timestamps:
            pairs = ", ".join(f'{{"{c}", type datetime}}' for c in timestamps)
            steps.append(f"\t\t\t\t    Types = Table.TransformColumnTypes(Donnees, {{{pairs}}})")
            result = "Types"
        lines += [
            "",
            f"\tpartition {table} = m",
            "\t\tmode: import",
            "\t\tsource =",
            *steps,
            "\t\t\t\tin",
            f"\t\t\t\t    {result}",
            "",
            "\tannotation PBI_ResultType = Table",
            "",
        ]
        write(definition / "tables" / f"{table}.tmdl", "\n".join(lines))

    relationships = []
    for fact, key, dimension, dim_key in RELATIONSHIPS:
        relationships += [
            f"relationship {tag(f'{fact}.{key}->{dimension}.{dim_key}')}",
            f"\tfromColumn: {fact}.{key}",
            f"\ttoColumn: {dimension}.{dim_key}",
            "\tcrossFilteringBehavior: oneDirection",
            "",
        ]
    write(definition / "relationships.tmdl", "\n".join(relationships))

    measures = ["table Mesures", "\tlineageTag: " + tag("Mesures")]
    for name, expression, fmt, folder, description in MEASURES:
        measures += [
            "",
            f"\t/// {description}",
            f"\tmeasure {name} = {expression}",
            "\t\tlineageTag: " + tag("Mesures." + name),
            f"\t\tdisplayFolder: {folder}",
        ]
        if fmt:
            measures.append(f"\t\tformatString: {fmt}")
    measures += [
        "",
        "\tcolumn _Mesures",
        "\t\tdataType: int64",
        "\t\tisHidden",
        "\t\tsourceColumn: _Mesures",
        "\t\tsummarizeBy: none",
        "",
        "\tpartition Mesures = m",
        "\t\tmode: import",
        "\t\tsource = #table(type table [_Mesures = Int64.Type], {{1}})",
        "",
    ]
    write(definition / "tables" / "Mesures.tmdl", "\n".join(measures))
    write(definition / "tables" / "Actualisation.tmdl", "\n".join([
        "table Actualisation",
        "\tisHidden",
        "\tlineageTag: " + tag("Actualisation"),
        "",
        "\tcolumn actualise_le",
        "\t\tdataType: dateTime",
        "\t\tsourceColumn: actualise_le",
        "\t\tformatString: dd/MM/yyyy HH:mm",
        "\t\tsummarizeBy: none",
        "",
        "\tpartition Actualisation = m",
        "\t\tmode: import",
        "\t\tsource =",
        '\t\t\t\tPostgreSQL.Database(ServeurPostgreSQL, BasePostgreSQL, [Query="SELECT '
        "(now() at time zone 'UTC') AS actualise_le\"])",
        "",
    ]))
    save(MODEL / "definition.pbism", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/item/semanticModel/"
                   "definitionProperties/1.0.0/schema.json",
        "version": "4.0",
        "settings": {},
    })
    save(BI / "FDIC.pbip", {
        "$schema": "https://developer.microsoft.com/json-schemas/fabric/pbip/pbipProperties/"
                   "1.0.0/schema.json",
        "version": "1.0",
        "artifacts": [{"report": {"path": "FDIC.Report"}}],
        "settings": {"enableAutoRecovery": True},
    })


# ---------------------------------------------------------------- report (PBIR)

SCHEMA_URL = "https://developer.microsoft.com/json-schemas/fabric/item/report/"
NAVY, TEAL, GRAY = "#132C45", "#087F8C", "#607286"
PALE, WHITE, RED = "#F3F6FA", "#FFFFFF", "#B23A3A"


def literal(value):
    if isinstance(value, bool):
        token = str(value).lower()
    elif isinstance(value, (float, int)):
        token = f"{value}D"
    else:
        token = "'" + str(value).replace("'", "''") + "'"
    return {"expr": {"Literal": {"Value": token}}}


def color(value):
    return {"solid": {"color": literal(value)}}


def properties(**values):
    return [{"properties": values}]


def column(table, name, label=None):
    return {
        "field": {"Column": {"Expression": {"SourceRef": {"Entity": table}}, "Property": name}},
        "queryRef": f"{table}.{name}",
        "nativeQueryRef": name,
        "displayName": label or name,
        "active": True,
    }


def measure(name, label=None):
    return {
        "field": {
            "Measure": {"Expression": {"SourceRef": {"Entity": "Mesures"}}, "Property": name}
        },
        "queryRef": f"Mesures.{name}",
        "nativeQueryRef": name,
        "displayName": label or name,
    }


def container(title, background=WHITE):
    return {
        "title": properties(
            show=literal(bool(title)), text=literal(title), fontColor=color(NAVY),
            fontSize=literal(13), bold=literal(True), fontFamily=literal("Segoe UI"),
        ),
        "background": properties(show=literal(True), color=color(background),
                                 transparency=literal(0)),
        "border": properties(show=literal(False)),
        "padding": properties(top=literal(14), bottom=literal(10), left=literal(16),
                              right=literal(16)),
        "visualHeader": properties(show=literal(True)),
    }


class Page:
    def __init__(self, key, title, subtitle, footer):
        self.key = key
        self.path = REPORT / "definition" / "pages" / key
        self.index = 0
        save(self.path / "page.json", {
            "$schema": SCHEMA_URL + "definition/page/2.0.0/schema.json",
            "name": key,
            "displayName": title,
            "displayOption": "FitToPage",
            "width": 1440,
            "height": 900,
            "objects": {
                "background": properties(color=color(PALE), transparency=literal(0)),
                "outspace": properties(color=color(PALE)),
            },
        })
        self.text("header", f"FDIC  /  {title.upper()}", 32, 24, 1376, 56, 24, WHITE, NAVY,
                  bold=True)
        self.text("subtitle", subtitle, 32, 87, 440, 64, 12, GRAY)
        self.text("footer", footer, 32, 862, 1376, 30, 9, GRAY)

    def visual(self, key, kind, title, x, y, width, height, roles=None, objects=None,
               sort=None):
        self.index += 1
        visual = {
            "visualType": kind,
            "visualContainerObjects": container(title),
            "drillFilterOtherVisuals": True,
        }
        if roles:
            visual["query"] = {
                "queryState": {role: {"projections": fields} for role, fields in roles.items()}
            }
            if sort:
                projection, direction = sort
                visual["query"]["sortDefinition"] = {
                    "sort": [{"field": projection["field"], "direction": direction}],
                    "isDefaultSort": False,
                }
        if objects:
            visual["objects"] = objects
        result = {
            "$schema": SCHEMA_URL + "definition/visualContainer/2.4.0/schema.json",
            "name": key,
            "position": {"x": x, "y": y, "width": width, "height": height,
                         "z": self.index * 1000, "tabOrder": self.index},
            "visual": visual,
        }
        save(self.path / "visuals" / key / "visual.json", result)
        return result

    def text(self, key, text, x, y, width, height, size, text_color, background=PALE,
             bold=False):
        d = self.visual(key, "textbox", "", x, y, width, height, objects={
            "general": properties(paragraphs=[{"textRuns": [{
                "value": text,
                "textStyle": {"fontFamily": "Segoe UI", "fontSize": f"{size}pt",
                              "color": text_color,
                              "fontWeight": "bold" if bold else "normal"},
            }]}])
        })
        d["visual"]["visualContainerObjects"] = {
            "background": properties(show=literal(True), color=color(background),
                                     transparency=literal(0)),
            "border": properties(show=literal(False)),
            "visualHeader": properties(show=literal(False)),
        }
        save(self.path / "visuals" / key / "visual.json", d)

    def card(self, index, name, label, accent=TEAL):
        self.visual(f"kpi_{name.lower()}", "cardVisual", "", 32 + index * 352, 166, 320, 116,
                    {"Data": [measure(name, label)]},
                    {"accentBar": [{
                        "properties": {"show": literal(True), "color": color(accent),
                                       "width": literal(4), "position": literal("Left")},
                        "selector": {"id": "default"},
                    }]})

    def slicer(self, key, label, field, x, width=296, single=False):
        self.visual(key, "slicer", label, x, 94, width, 62, {"Values": [field]}, {
            "data": properties(mode=literal("Dropdown")),
            "selection": properties(singleSelect=literal(single),
                                    selectAllCheckboxEnabled=literal(not single)),
            "header": properties(show=literal(False)),
        })

    def table(self, key, title, x, y, width, height, fields, sort=None):
        self.visual(key, "tableEx", title, x, y, width, height, {"Values": fields},
                    table_objects(), sort)


def chart_objects(labels=False):
    return {
        "legend": properties(show=literal(False)),
        "categoryAxis": properties(showAxisTitle=literal(False), labelColor=color(GRAY),
                                   fontSize=literal(10)),
        "valueAxis": properties(showAxisTitle=literal(False), labelColor=color(GRAY),
                                fontSize=literal(10), gridlineColor=color("#E6ECF2")),
        "labels": properties(show=literal(labels), color=color(NAVY), fontSize=literal(10)),
    }


def table_objects():
    return {
        "grid": properties(rowPadding=literal(6), textSize=literal(10),
                           gridVertical=literal(False), gridHorizontal=literal(True),
                           gridHorizontalColor=color("#E6ECF2")),
        "columnHeaders": properties(fontColor=color(NAVY), backColor=color("#E7EFF5"),
                                    bold=literal(True), fontSize=literal(10),
                                    wordWrap=literal(True)),
        "values": properties(fontColorPrimary=color(NAVY), backColorPrimary=color(WHITE),
                             backColorSecondary=color("#F7F9FB"), fontSize=literal(10)),
        "total": properties(totals=literal(False)),
    }


def page_overview():
    p = Page(
        "vue_ensemble", "Vue d'ensemble",
        "Santé du secteur bancaire américain, trimestre par trimestre.",
        "Source : FDIC BankFind Suite, déclarations trimestrielles (Call Reports), montants en "
        "milliards de dollars. Les stocks sont lus au dernier trimestre sélectionné ; le résultat "
        "est le flux du trimestre seul. Seules les données publiées (tous les tests dbt réussis) "
        "sont lues.",
    )
    quarter = column("fct_filings", "report_quarter_label", "Trimestre")
    p.slicer("filtre_trimestre", "Trimestre", quarter, 488)
    p.slicer("filtre_etat", "État", column("fct_filings", "state_code", "État"), 800)
    p.slicer("filtre_taille", "Taille", column("fct_filings", "asset_size_group", "Taille"), 1112)
    for i, (name, label) in enumerate([
        ("Banques", "Banques déclarantes"),
        ("ActifsMd", "Actifs · Md$"),
        ("DepotsMd", "Dépôts · Md$"),
        ("ResultatTrimestreMd", "Résultat du trimestre · Md$"),
    ]):
        p.card(i, name, label)
    p.visual("actifs", "clusteredColumnChart", "Actifs par trimestre · Md$", 32, 298, 680, 260,
             {"Category": [quarter], "Y": [measure("ActifsMd", "Actifs")]},
             chart_objects(), (quarter, "Ascending"))
    p.visual("resultat", "clusteredColumnChart", "Résultat net du trimestre · Md$", 728, 298,
             680, 260, {"Category": [quarter], "Y": [measure("ResultatTrimestreMd", "Résultat")]},
             chart_objects(True), (quarter, "Ascending"))
    size = column("fct_filings", "asset_size_group", "Taille")
    p.visual("tailles", "clusteredBarChart", "Banques par taille d'actifs", 32, 574, 440, 280,
             {"Category": [size], "Y": [measure("Banques", "Banques")]},
             chart_objects(True), (size, "Ascending"))
    assets = measure("ActifsMd", "Actifs · Md$")
    p.table("principales", "Principales banques", 488, 574, 920, 280, [
        column("fct_filings", "institution_name", "Banque"),
        column("fct_filings", "state_code", "État"),
        assets,
        measure("FondsPropresSurActifs", "Fonds propres / actifs"),
        measure("ROAPublie", "ROA"),
        measure("ResultatTrimestreMd", "Résultat · Md$"),
    ], (assets, "Descending"))


def page_institution():
    p = Page(
        "etablissement", "Fiche établissement",
        "Choisir une banque : chaque chiffre remonte à son lot source.",
        "Lot : extraction de l'API FDIC qui a fourni la valeur courante (batch_id, version de "
        "l'index FDIC, date d'extraction). Versions : chaque contenu distinct observé, avec sa "
        "raison (initial, changement de contrat, révision FDIC, simulation).",
    )
    p.slicer("filtre_banque", "Banque", column("dim_institution", "institution_name", "Banque"),
             488, 920, single=True)
    for i, (name, label) in enumerate([
        ("ActifsMd", "Actifs · Md$"),
        ("FondsPropresSurActifs", "Fonds propres / actifs"),
        ("ROAPublie", "ROA"),
        ("PretsNonPerformants", "Prêts non performants"),
    ]):
        p.card(i, name, label)
    quarter = column("fct_filings", "report_quarter_label", "Trimestre")
    p.table("declarations", "Déclarations et lot source", 32, 298, 1376, 300, [
        quarter,
        column("fct_filings", "total_assets_kusd", "Actifs · k$"),
        column("fct_filings", "equity_capital_kusd", "Fonds propres · k$"),
        column("fct_filings", "net_income_qtr_kusd", "Résultat du trimestre · k$"),
        column("fct_filings", "equity_to_assets_pct", "FP / actifs %"),
        column("fct_filings", "roa_pct", "ROA %"),
        column("fct_filings", "signal_count", "Signaux"),
        column("fct_filings", "batch_id", "Lot source"),
        column("fct_filings", "source_index_name", "Index FDIC"),
        column("fct_filings", "extracted_at", "Extrait le"),
        column("fct_filings", "version_count", "Versions"),
    ], (quarter, "Descending"))
    valid_from = column("fct_filing_versions", "valid_from", "Depuis")
    p.table("versions", "Versions de chaque déclaration", 32, 614, 680, 240, [
        column("fct_filing_versions", "report_date", "Trimestre"),
        column("fct_filing_versions", "version_number", "Version"),
        column("fct_filing_versions", "change_kind", "Raison"),
        column("fct_filing_versions", "changed_fields", "Champs modifiés"),
        column("fct_filing_versions", "batch_id", "Lot"),
        valid_from,
    ], (valid_from, "Descending"))
    p.table("revisions", "Valeurs modifiées", 728, 614, 680, 240, [
        column("rpt_filing_revisions", "report_date", "Trimestre"),
        column("rpt_filing_revisions", "source_field", "Champ"),
        column("rpt_filing_revisions", "previous_value", "Avant"),
        column("rpt_filing_revisions", "new_value", "Après"),
        column("rpt_filing_revisions", "change_kind", "Raison"),
    ])


def page_early_warning():
    p = Page(
        "alerte", "Alerte précoce",
        "Les signaux étaient-ils visibles avant les faillites ?",
        "Signaux, seuils dans dbt_project.yml : capital (levier Tier 1 < 5 %), qualité des actifs "
        "(prêts non performants > 5 %), résultat (ROA < 0). Filtre illustratif, pas une notation "
        "prudentielle. Cas de référence : CERT 25796, faillite le 01/05/2026.",
    )
    for i, (name, label, accent) in enumerate([
        ("FaillitesCouvertes", "Faillites couvertes", TEAL),
        ("FaillitesSignalees", "Dont signalées (≥ 2 signaux)", RED),
        ("ListeSurveillance", "Banques sous surveillance", RED),
        ("TroisSignaux", "Dont trois signaux", RED),
    ]):
        p.card(i, name, label, accent)
    failure = column("rpt_failure_signals", "failure_date", "Faillite")
    p.table("historique", "Déclarations avant chaque faillite", 32, 298, 1376, 280, [
        column("rpt_failure_signals", "institution_name", "Banque"),
        failure,
        column("rpt_failure_signals", "report_quarter_label", "Trimestre"),
        column("rpt_failure_signals", "quarters_before_failure", "Trimestres avant"),
        column("rpt_failure_signals", "noncurrent_loans_ratio_pct", "Prêts non perf. %"),
        column("rpt_failure_signals", "equity_to_assets_pct", "FP / actifs %"),
        column("rpt_failure_signals", "tier1_leverage_ratio_pct", "Levier Tier 1 %"),
        column("rpt_failure_signals", "roa_pct", "ROA %"),
        column("rpt_failure_signals", "signal_count", "Signaux"),
    ], (failure, "Ascending"))
    signals = column("rpt_watchlist", "signal_count", "Signaux")
    p.table("surveillance", "Liste de surveillance · dernier trimestre", 32, 594, 1376, 260, [
        column("rpt_watchlist", "institution_name", "Banque"),
        column("rpt_watchlist", "state_code", "État"),
        column("rpt_watchlist", "asset_size_group", "Taille"),
        column("rpt_watchlist", "noncurrent_loans_ratio_pct", "Prêts non perf. %"),
        column("rpt_watchlist", "tier1_leverage_ratio_pct", "Levier Tier 1 %"),
        column("rpt_watchlist", "roa_pct", "ROA %"),
        signals,
        column("rpt_watchlist", "previous_signal_count", "Trimestre précédent"),
    ], (signals, "Descending"))


def page_quality():
    p = Page(
        "qualite", "Qualité et lignage",
        "Ce qui a été extrait, refusé, rapproché et publié.",
        "Rapprochement REC-02 avec le Quarterly Banking Profile de la FDIC : même population "
        "(établissements assurés), tolérance de 0,5 %. Un lot « duplicate » est un rejeu "
        "identique : il est tracé, rien n'est chargé.",
    )
    for i, (name, label) in enumerate([
        ("LotsCharges", "Lots chargés"),
        ("LotsDoublons", "Rejeux identiques"),
        ("LotsEchecs", "Lots refusés"),
        ("Rapprochements", "Contrôles QBP conformes"),
    ]):
        p.card(i, name, label)
    quarter = column("rpt_reconciliation_qbp", "report_quarter_label", "Trimestre")
    p.table("rapprochement", "Rapprochement avec le Quarterly Banking Profile", 32, 298, 680,
            300, [
                quarter,
                column("rpt_reconciliation_qbp", "measure", "Mesure"),
                column("rpt_reconciliation_qbp", "reference_value", "QBP"),
                column("rpt_reconciliation_qbp", "warehouse_value", "Entrepôt"),
                column("rpt_reconciliation_qbp", "relative_gap", "Écart"),
                column("rpt_reconciliation_qbp", "status", "Statut"),
            ], (quarter, "Ascending"))
    status = column("rpt_batches", "status", "Statut")
    p.visual("statuts", "clusteredBarChart", "Lots par statut", 728, 298, 680, 300,
             {"Category": [status], "Y": [measure("LotsCharges", "Lots")]},
             chart_objects(True))
    started = column("rpt_batches", "started_at", "Début")
    p.table("lots", "Registre des lots", 32, 614, 1376, 240, [
        column("rpt_batches", "batch_id", "Lot"),
        column("rpt_batches", "mode", "Mode"),
        status,
        column("rpt_batches", "contract_version", "Contrat"),
        column("rpt_batches", "rows_announced", "Annoncées"),
        column("rpt_batches", "rows_loaded", "Chargées"),
        column("rpt_batches", "duration_seconds", "Durée · s"),
        started,
        column("rpt_batches", "error", "Erreur"),
    ], (started, "Descending"))


PAGES = {
    "vue_ensemble": page_overview,
    "etablissement": page_institution,
    "alerte": page_early_warning,
    "qualite": page_quality,
}


def build_report() -> None:
    shutil.rmtree(REPORT / "definition", ignore_errors=True)
    save(REPORT / "definition.pbir", {
        "$schema": SCHEMA_URL + "definitionProperties/2.0.0/schema.json",
        "version": "4.0",
        "datasetReference": {"byPath": {"path": "../FDIC.SemanticModel"}},
    })
    save(REPORT / "definition" / "version.json", {
        "$schema": SCHEMA_URL + "definition/versionMetadata/1.0.0/schema.json",
        "version": "2.0.0",
    })
    save(REPORT / "StaticResources" / "RegisteredResources" / "FDIC.json", {
        "name": "FDIC",
        "dataColors": [TEAL, "#2471A3", "#E6A23C", "#7C6CC4", "#51A793", RED, "#5E8DB5", NAVY],
        "background": WHITE,
        "foreground": NAVY,
        "tableAccent": TEAL,
        "good": "#269977",
        "neutral": "#E6A23C",
        "bad": RED,
        "textClasses": {
            "label": {"fontFace": "Segoe UI", "fontSize": 11, "color": GRAY},
            "callout": {"fontFace": "Segoe UI Semibold", "fontSize": 28, "color": NAVY},
            "title": {"fontFace": "Segoe UI Semibold", "fontSize": 13, "color": NAVY},
            "header": {"fontFace": "Segoe UI", "fontSize": 12, "color": NAVY},
        },
    })
    save(REPORT / "definition" / "report.json", {
        "$schema": SCHEMA_URL + "definition/report/3.0.0/schema.json",
        "themeCollection": {"customTheme": {
            "name": "FDIC.json",
            "reportVersionAtImport": {"visual": "2.4.0", "report": "3.0.0", "page": "2.0.0"},
            "type": "RegisteredResources",
        }},
        "resourcePackages": [{
            "name": "RegisteredResources",
            "type": "RegisteredResources",
            "items": [{"name": "FDIC.json", "path": "FDIC.json", "type": "CustomTheme"}],
        }],
        "settings": {
            "useStylableVisualContainerHeader": True,
            "exportDataMode": "AllowSummarized",
            "defaultDrillFilterOtherVisuals": True,
            "useEnhancedTooltips": True,
        },
    })
    save(REPORT / "definition" / "pages" / "pages.json", {
        "$schema": SCHEMA_URL + "definition/pagesMetadata/1.0.0/schema.json",
        "pageOrder": list(PAGES),
        "activePageName": "vue_ensemble",
    })
    for build_page in PAGES.values():
        build_page()


def main() -> None:
    schema = read_schema()
    build_model(schema)
    build_report()
    visuals = sum(1 for _ in REPORT.rglob("visual.json"))
    print(f"model: {len(TABLES)} tables, {len(RELATIONSHIPS)} relationships, "
          f"{len(MEASURES)} measures; report: {len(PAGES)} pages, {visuals} visuals")
    print(f"open {BI / 'FDIC.pbip'} in Power BI Desktop, then refresh with the fdic_reader login")


if __name__ == "__main__":
    main()
