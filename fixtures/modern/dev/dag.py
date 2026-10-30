"""Synthetic definition-only Airflow DAG. The scanner must not import this file."""
from airflow import DAG
from airflow.operators.bash import BashOperator

with DAG(dag_id="warehouse_orders", schedule="0 3 * * *", catchup=False) as dag:
    stage = BashOperator(task_id="stage", bash_command="dbt run --select staging_orders")
    publish = BashOperator(task_id="publish", bash_command="dbt run --select final_orders")
    stage >> publish
