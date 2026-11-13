"""Create Airflow's metadata database next to the warehouse, if it does not exist yet."""

import os

import psycopg
from psycopg import sql

conninfo = psycopg.conninfo.make_conninfo(
    host=os.environ["POSTGRES_HOST"],
    port=os.environ["POSTGRES_PORT"],
    dbname=os.environ.get("POSTGRES_DB", "fdic_dwh"),
    user=os.environ.get("POSTGRES_USER", "fdic"),
    password=os.environ["POSTGRES_PASSWORD"],
)
with psycopg.connect(conninfo, autocommit=True) as conn:
    if not conn.execute("select 1 from pg_database where datname = 'airflow'").fetchone():
        conn.execute(sql.SQL("create database {}").format(sql.Identifier("airflow")))
        print("created database airflow")
