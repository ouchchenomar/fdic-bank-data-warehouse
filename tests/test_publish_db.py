"""Gated publication (DWH-05): refused builds never reach the published views."""

from __future__ import annotations

import psycopg
import pytest

from fdic_dwh.publish import _LOCK, BuildResult, publish, rollback

pytestmark = pytest.mark.db

TABLES = ("dim_x", "fct_x")
PASSED = BuildResult(True, {"pass": 12})


def failed_build():
    return BuildResult(False, {"pass": 11, "fail": 1}, ["assert_published_ratios (fail: 1)"])


@pytest.fixture
def marts(pg):
    """A fake marts schema, and no publication left from an earlier test."""
    for (schema,) in pg.execute(
        "select schema_name from information_schema.schemata"
        " where schema_name like 'pub\\_%' or schema_name in ('published', 'marts_test')"
    ).fetchall():
        pg.execute(f'drop schema "{schema}" cascade')
    pg.execute("create schema marts_test")
    pg.execute("create table marts_test.dim_x as select 1 as cert")
    pg.execute("create table marts_test.fct_x as select g as n from generate_series(1, 3) g")
    pg.commit()
    return pg


def run(pg, build=lambda: PASSED, **kwargs):
    return publish(pg, build, source_schema="marts_test", tables=TABLES, **kwargs)


def published_rows(pg, table="fct_x"):
    return pg.execute(f"select count(*) from published.{table}").fetchone()[0]


def view_target(pg, table="fct_x"):
    return pg.execute(
        "select distinct table_schema from information_schema.view_table_usage"
        " where view_schema = 'published' and view_name = %s",
        (table,),
    ).fetchone()[0]


def test_passing_build_is_published(marts):
    outcome = run(marts)
    assert outcome.status == "published"
    assert outcome.previous_schema is None
    assert outcome.table_rows == {"dim_x": 1, "fct_x": 3}
    assert view_target(marts) == outcome.target_schema
    assert published_rows(marts) == 3


def test_failed_build_is_refused_and_published_views_stay(marts):
    first = run(marts)
    marts.execute("insert into marts_test.fct_x values (4)")
    marts.commit()

    outcome = run(marts, build=failed_build)

    assert outcome.status == "refused"
    assert "assert_published_ratios" in outcome.error
    assert outcome.previous_schema == first.target_schema
    assert view_target(marts) == first.target_schema
    assert published_rows(marts) == 3


def test_crashed_build_is_refused(marts):
    def crash():
        raise RuntimeError("dbt could not connect")

    outcome = run(marts, build=crash)
    assert outcome.status == "refused"
    assert "dbt could not connect" in outcome.error


def test_copy_error_is_refused_without_leftovers(marts):
    first = run(marts)
    marts.execute("drop table marts_test.dim_x")
    marts.commit()

    outcome = run(marts)

    assert outcome.status == "refused"
    assert "dim_x" in outcome.error
    assert view_target(marts) == first.target_schema
    assert not marts.execute(
        "select 1 from information_schema.schemata where schema_name = %s",
        (outcome.publication_id,),
    ).fetchone()


def test_only_the_last_publications_are_kept(marts):
    outcomes = [run(marts, keep=2) for _ in range(3)]
    schemas = {
        r[0]
        for r in marts.execute(
            "select schema_name from information_schema.schemata where schema_name like 'pub\\_%'"
        )
    }
    assert schemas == {outcomes[1].target_schema, outcomes[2].target_schema}


def test_rollback_points_back_to_the_previous_publication(marts):
    first = run(marts)
    marts.execute("insert into marts_test.fct_x values (4)")
    marts.commit()
    second = run(marts)
    assert published_rows(marts) == 4

    assert rollback(marts, tables=TABLES) == first.target_schema

    assert view_target(marts) == first.target_schema
    assert published_rows(marts) == 3
    status = marts.execute(
        "select status from ops.publication where publication_id = %s", (second.publication_id,)
    ).fetchone()[0]
    assert status == "rolled_back"


def test_rollback_needs_an_earlier_publication(marts):
    run(marts)
    with pytest.raises(LookupError):
        rollback(marts, tables=TABLES)


def test_one_publication_at_a_time(marts, test_conninfo):
    with psycopg.connect(test_conninfo) as other:
        other.execute("select pg_advisory_lock(%s)", (_LOCK,))
        with pytest.raises(RuntimeError, match="another publication"):
            run(marts)
        other.execute("select pg_advisory_unlock(%s)", (_LOCK,))
    assert run(marts).status == "published"
