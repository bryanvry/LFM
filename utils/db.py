import streamlit as st
import pandas as pd
from sqlalchemy import text
from datetime import datetime
from utils.helpers import _norm_upc_12

def get_db_connection():
    return st.connection("supabase", type="sql")    

def log_activity(store, vendor, items_cnt, changes_cnt):
    try:
        conn = get_db_connection()
        log_data = pd.DataFrame([{
            "store": store, "vendor": vendor, "items_found": int(items_cnt),
            "price_changes_found": int(changes_cnt), "created_at": datetime.now()
        }])
        log_data.to_sql("invoice_history", conn.engine, if_exists='append', index=False)
    except Exception as e:
        pass

def load_pricebook(table_name):
    conn = get_db_connection()
    query = f'SELECT * FROM "{table_name}"'
    try:
        df = conn.query(query, ttl=0) 
        df["_norm_upc"] = df["Upc"].apply(_norm_upc_12)
        return df
    except Exception as e:
        st.error(f"Error loading Pricebook ({table_name}): {e}")
        return pd.DataFrame()

def load_vendor_map(table_name):
    conn = get_db_connection()
    query = f'SELECT * FROM "{table_name}"'
    try:
        df = conn.query(query, ttl=0)
        if not df.empty: df["_inv_upc_norm"] = df["Invoice UPC"].apply(_norm_upc_12)
        return df
    except Exception as e:
        st.error(f"Error loading Vendor Map: {e}")
        return pd.DataFrame()

def load_jcsales_key():
    conn = get_db_connection()
    query = 'SELECT * FROM "JCSalesKey"'
    try:
        df = conn.query(query, ttl=0)
        return df
    except Exception as e:
        st.error(f"Error loading JC Sales Key: {e}")
        return pd.DataFrame()

def get_last_upload_time(table_name):
    try:
        conn = get_db_connection()
        df = conn.query(f"SELECT last_uploaded FROM admin_upload_logs WHERE table_name = '{table_name}'", ttl=0)
        if not df.empty:
            raw_time = pd.to_datetime(df.iloc[0]['last_uploaded'])
            if raw_time.tzinfo is None: raw_time = raw_time.tz_localize('UTC')
            return raw_time.tz_convert('America/Los_Angeles').strftime("%Y-%m-%d %I:%M %p")
    except Exception:
        pass
    return "Never / Unknown"

def set_last_upload_time(table_name):
    try:
        conn = get_db_connection()
        with conn.session as session:
            session.execute(text('''
                INSERT INTO admin_upload_logs (table_name, last_uploaded) 
                VALUES (:tbl, NOW()) ON CONFLICT (table_name) DO UPDATE SET last_uploaded = NOW();
            '''), {"tbl": table_name})
            session.commit()
    except Exception as e:
        pass
