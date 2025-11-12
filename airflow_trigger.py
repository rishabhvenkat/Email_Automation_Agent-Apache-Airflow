from fastapi import APIRouter, Depends, HTTPException
from airflow_client.client.api.dag_run_api import DAGRunApi
from airflow_client.client.model.dag_run import DAGRun
from airflow_client.client import ApiClient, Configuration
from sqlalchemy.ext.asyncio import AsyncSession
import uuid

from crud import fetch_user_input_folder
from database import get_db_connection
from schemas import UserInfoCRUD

router = APIRouter()

@router.post("/aqua/trigger-etl", tags=["ETL"])
async def trigger_email_etl(payload: UserInfoCRUD, db: AsyncSession = Depends(get_db_connection)):
    try:
        input_folder = await fetch_user_input_folder(db, user_id=payload.data.email_id)
        if not input_folder:
            raise HTTPException(status_code=404, detail="User email/folder not found.")

        configuration = Configuration(host="http://localhost:8080/api/v1")
        with ApiClient(configuration) as api_client:
            dag_api = DAGRunApi(api_client)

            run_id = f"etl_run_{str(uuid.uuid4())[:8]}"
            dag_run = DAGRun(
                conf={
                    "user_email": payload.data.email_id,
                    "folder_names": [input_folder]
                },
                run_id=run_id
            )
            dag_api.post_dag_run(dag_id="ms_graph_email_etl_postgres", dag_run=dag_run)

        return {
            "status": "success",
            "message": "ETL triggered",
            "data": {"run_id": run_id},
            "error": None
        }

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
