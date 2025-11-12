import psycopg2
import pandas as pd
import os

def get_connection():
    return psycopg2.connect(
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
        host=os.getenv("DB_HOST"),
        port=os.getenv("DB_PORT", "5432")
    )

def get_folders():
    conn = get_connection()
    df = pd.read_sql("SELECT DISTINCT folder FROM email_group;", conn)
    conn.close()
    return df['folder'].tolist()

def get_email_data(folder=None):
    conn = get_connection()
    query = f"SELECT * FROM email_group"
    if folder:
        query += f" WHERE folder = '{folder}'"
    df = pd.read_sql(query, conn)
    conn.close()
    return df

def get_response_data():
    conn = get_connection()
    df = pd.read_sql("SELECT * FROM email_response", conn)
    conn.close()
    return df
