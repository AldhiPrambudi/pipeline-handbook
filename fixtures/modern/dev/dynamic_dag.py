"""Deliberately unsupported runtime-generated graph, never imported by scanner."""
from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(dag_id="dynamic_unknown", schedule=None) as dag:
    for name in ["one", "two"]:
        BashOperator(task_id=name, bash_command="echo synthetic")
