from airflow import DAG
from airflow.decorators import task
from airflow.sdk import Variable
from airflow.providers.postgres.hooks.postgres import PostgresHook
from datetime import datetime, timedelta
import requests
import json
import os
import pandas as pd
import logging

POSTGRES_CONN_ID = 'postgres_default'

default_args = {
    'owner': 'airflow',
    'start_date': datetime(2024, 1, 1),
    'retries': 1,
    'retry_delay': timedelta(minutes=5)
}

with DAG(
    dag_id='ms_graph_email_etl_postgres',
    default_args=default_args,
    schedule='@daily',
    catchup=False,
    tags=['email', 'graph', 'etl', 'postgres']
) as dag:

    @task()
    def get_graph_token():
        tenant_id = os.environ.get("MS_GRAPH_TENANT_ID")
        client_id = os.environ.get("MS_GRAPH_CLIENT_ID")
        client_secret = os.environ.get("MS_GRAPH_CLIENT_SECRET")

        url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"
        headers = {"Content-Type": "application/x-www-form-urlencoded"}
        data = {
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "client_credentials",
            "scope": "https://graph.microsoft.com/.default"
        }

        response = requests.post(url, headers=headers, data=data)
        if response.status_code == 200:
            return response.json()['access_token']
        else:
            raise Exception(f"Failed to get token: {response.status_code} - {response.text}")

    @task()
    def extract_emails_from_folders(access_token: str):
        graph_base = "https://graph.microsoft.com/v1.0"
        user_email = Variable.get("MS_GRAPH_USER_EMAIL")
        folder_names = json.loads(Variable.get("MS_GRAPH_FOLDER_NAMES", default='["Inbox"]'))

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json"
        }

        def get_folder_id(folder_name):
            if folder_name.strip().lower() == "inbox":
                inbox_url = f"{graph_base}/users/{user_email}/mailFolders/Inbox"
                response = requests.get(inbox_url, headers=headers)
                if response.status_code == 200:
                    return response.json()["id"]
                else:
                    raise Exception(f"Error fetching Inbox: {response.status_code}, {response.text}")
            else:
                inbox_url = f"{graph_base}/users/{user_email}/mailFolders/Inbox/childFolders"
                response = requests.get(inbox_url, headers=headers)
                if response.status_code == 200:
                    folders = response.json().get("value", [])
                    for folder in folders:
                        if folder["displayName"].strip().lower() == folder_name.strip().lower():
                            return folder["id"]
                raise Exception(f"Folder '{folder_name}' not found.")

        def fetch_emails(folder_id):
            emails = []
            url = f"{graph_base}/users/{user_email}/mailFolders/{folder_id}/messages?$orderby=receivedDateTime desc"
            while url:
                response = requests.get(url, headers=headers)
                if response.status_code == 200:
                    data = response.json()
                    emails.extend(data.get("value", []))
                    url = data.get("@odata.nextLink", None)
                else:
                    raise Exception(f"Error fetching emails: {response.status_code}, {response.text}")
            return emails

        all_emails = {}
        for folder_name in folder_names:
            folder_id = get_folder_id(folder_name)
            emails = fetch_emails(folder_id)
            all_emails[folder_name] = emails

        return {"emails_by_folder": all_emails, "user_email": user_email}

    @task()
    def load_to_postgres(data):
        if data is None:
            raise ValueError("No data passed to load_to_postgres")

        all_emails = data.get("emails_by_folder", {})
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        conn = pg_hook.get_conn()
        cursor = conn.cursor()

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_group (
                email_id TEXT PRIMARY KEY,
                thread_id TEXT,
                from_name TEXT,
                from_email TEXT,
                subject TEXT,
                received_date DATE,
                received_time TIME,
                full_received_datetime TIMESTAMP WITH TIME ZONE,
                folder TEXT
            );
        """)

        for folder_name, emails in all_emails.items():
            for msg in emails:
                try:
                    full_received_dt = msg.get('receivedDateTime', '')
                    cursor.execute("""
                        INSERT INTO email_group (
                            email_id, thread_id, from_name, from_email,
                            subject, received_date, received_time, full_received_datetime, folder
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (email_id) DO NOTHING;
                    """, (
                        msg['id'],
                        msg.get('conversationId'),
                        msg.get('from', {}).get('emailAddress', {}).get('name'),
                        msg.get('from', {}).get('emailAddress', {}).get('address'),
                        msg.get('subject', ''),
                        full_received_dt[:10],
                        full_received_dt[11:19],
                        full_received_dt,
                        folder_name
                    ))
                except Exception as e:
                    print(f"[ERROR] Failed to insert email id {msg.get('id')}: {e}")

        conn.commit()
        cursor.close()

    @task()
    def compute_response_metrics():
        pg_hook = PostgresHook(postgres_conn_id=POSTGRES_CONN_ID)
        conn = pg_hook.get_conn()
        cursor = conn.cursor()

        df = pd.read_sql("SELECT * FROM email_group ORDER BY thread_id, full_received_datetime", conn)

        # Ensure datetime is timezone-aware
        df['received_datetime'] = pd.to_datetime(df['full_received_datetime'], utc=True)

        response_metrics = []
        for thread_id, group in df.groupby('thread_id'):
            group = group.sort_values('received_datetime')
            if len(group) < 2:
                continue
            first_msg = group.iloc[0]
            reply_msg = group.iloc[1]
            response_time = (reply_msg['received_datetime'] - first_msg['received_datetime']).total_seconds()

            response_metrics.append({
                'thread_id': thread_id,
                'from_email': first_msg['from_email'],
                'folder': first_msg['folder'],
                'response_time_seconds': response_time
            })

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_response (
                thread_id TEXT PRIMARY KEY,
                from_email TEXT,
                folder TEXT,
                response_time_seconds FLOAT
            );
        """)

        for row in response_metrics:
            cursor.execute("""
                INSERT INTO email_response (thread_id, from_email, folder, response_time_seconds)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (thread_id) DO UPDATE SET
                    response_time_seconds = EXCLUDED.response_time_seconds;
            """, (
                row['thread_id'],
                row['from_email'],
                row['folder'],
                row['response_time_seconds']
            ))

        conn.commit()
        cursor.close()

    token = get_graph_token()
    email_data = extract_emails_from_folders(token)
    load = load_to_postgres(email_data)
    compute = compute_response_metrics()

    load >> compute
