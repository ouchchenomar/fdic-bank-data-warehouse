# Airflow only orchestrates. Each task runs `run.py` with the project's own virtual
# environment, so Airflow and dbt never share (and break) each other's dependencies.
# The project code is not copied: docker-compose.yml mounts the repository at /opt/fdic.
FROM apache/airflow:3.3.2-python3.12

USER root
COPY requirements.txt /tmp/fdic-requirements.txt
RUN python -m venv /opt/fdic-venv \
    && /opt/fdic-venv/bin/pip install --no-cache-dir -r /tmp/fdic-requirements.txt \
    && chown -R airflow: /opt/fdic-venv
USER airflow
