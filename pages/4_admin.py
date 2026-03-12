import streamlit as st
import pandas as pd
import psutil
import os
import time
from datetime import datetime
from sqlalchemy import text
from utils.db import get_db_connection, get_last_upload_time, set_last_upload_time, load_vendor_map, load_jcsales_key
from utils.helpers import to_xlsx_bytes, render_top_nav

st.set_page_config(page_title="Admin | LFM", layout="wide", initial_sidebar_state="collapsed")

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

render_top_nav()

selected_store = st.session_state["selected_store"]
PRICEBOOK_TABLE = st.session_state["PRICEBOOK_TABLE"]
SALES_TABLE = st.session_state["SALES_TABLE"]
VENDOR_MAP_TABLE = st.session_state["VENDOR_MAP_TABLE"]

st.header("Database Administration")

process = psutil.Process(os.getpid())
mem_info = process.memory_info()
ram_mb = mem_info.rss / (1024 * 1024) 
st.metric("⚡ Current App RAM Usage", f"{ram_mb:.2f} MB")
st.divider()

col_pb, col_map, col_jc = st.columns(3)

with col_pb:
    st.subheader(f"Update Pricebook ({selected_store})")
    st.caption(f"Target: `{PRICEBOOK_TABLE}`  \n⏳ Last Uploaded: **{get_last_upload_time(PRICEBOOK_TABLE)}**")
    pb_upload = st.file_uploader("Upload Pricebook CSV", type=["csv"], key="pb_admin")
    
    if pb_upload and st.button("Replace Pricebook", type="primary"):
        try:
            df = pd.read_csv(pb_upload, dtype=str)
            df.columns = [c.strip() for c in df.columns]
            upc_col = next((c for c in df.columns if c.lower() == 'upc'), None)
            if not upc_col: st.error("CSV must have a 'Upc' column.")
            else:
                df = df.rename(columns={upc_col: "Upc"})
                conn = get_db_connection()
                with conn.session as session:
                    session.execute(text(f'TRUNCATE TABLE "{PRICEBOOK_TABLE}";'))
                    session.commit()
                valid_cols = ["Upc", "Department", "qty", "cents", "setstock", "cost_qty", "cost_cents", "Name", "incltaxes", "inclfees", "size", "ebt", "byweight", "Fee Multiplier"]
                cols_to_use = [c for c in valid_cols if c in df.columns]
                df[cols_to_use].to_sql(PRICEBOOK_TABLE, conn.engine, if_exists='append', index=False)
                set_last_upload_time(PRICEBOOK_TABLE)
                st.success(f"Replaced {len(df)} rows in {PRICEBOOK_TABLE}.")
                time.sleep(1)
                st.rerun() 
        except Exception as e:
            st.error(f"Error updating pricebook: {e}")

with col_map:
    st.subheader(f"Update Vendor Map ({selected_store})")
    st.caption(f"Target: `{VENDOR_MAP_TABLE}`  \n⏳ Last Uploaded: **{get_last_upload_time(VENDOR_MAP_TABLE)}**")
    current_map = load_vendor_map(VENDOR_MAP_TABLE)
    if not current_map.empty:
        export_map = current_map.drop(columns=["_inv_upc_norm"], errors="ignore")
        st.download_button(label=f"⬇️ Download Current {selected_store} Map", data=to_xlsx_bytes({"VendorMap": export_map}), file_name=f"VendorMap_{selected_store}_{datetime.today().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
    
    map_upload = st.file_uploader("Upload Beer & Liquor Master xlsx", type=["xlsx"], key="map_admin")
    if map_upload and st.button("Replace Map", type="primary"):
        try:
            df = pd.read_excel(map_upload, dtype=str)
            if "Full Barcode" not in df.columns or "Invoice UPC" not in df.columns: st.error("File missing 'Full Barcode' or 'Invoice UPC'.")
            else:
                original_count = len(df)
                df = df.drop_duplicates(subset=["Invoice UPC"], keep="last")
                dropped_count = original_count - len(df)
                if dropped_count > 0: st.warning(f"🧹 Removed {dropped_count} duplicate Invoice UPCs from your upload.")

                conn = get_db_connection()
                target_cols = ["Full Barcode", "Invoice UPC", "0", "Name", "Size", "PACK", "Company", "type"]
                cols_to_load = [c for c in target_cols if c in df.columns]
                with conn.session as session:
                    session.execute(text(f'TRUNCATE TABLE "{VENDOR_MAP_TABLE}";'))
                    session.commit()
                df[cols_to_load].to_sql(VENDOR_MAP_TABLE, conn.engine, if_exists='append', index=False)
                set_last_upload_time(VENDOR_MAP_TABLE)
                st.success(f"Map replaced successfully with {len(df)} unique rows.")
                time.sleep(2)
                st.rerun() 
        except Exception as e:
            st.error(f"Error updating map: {e}")

with col_jc:
    st.subheader("Update JC Sales Key (Global)")
    st.caption(f"Target: `JCSalesKey`  \n⏳ Last Uploaded: **{get_last_upload_time('JCSalesKey')}**")
    current_jc = load_jcsales_key()
    if not current_jc.empty:
        st.download_button(label="⬇️ Download Current JC Sales Key", data=to_xlsx_bytes({"JCSalesKey": current_jc}), file_name=f"JCSalesKey_{datetime.today().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
        
    jc_upload = st.file_uploader("Upload JC Sales Key xlsx/csv", type=["xlsx", "csv"], key="jc_admin")
    if jc_upload and st.button("Replace JC Sales Key", type="primary"):
        try:
            df = pd.read_excel(jc_upload, dtype=str) if jc_upload.name.endswith('.xlsx') else pd.read_csv(jc_upload, dtype=str)
            target_cols = ["ITEM", "UPC1", "UPC2", "DESCRIPTION", "PACK", "COST"]
            cols_to_load = [c for c in target_cols if c in df.columns]
            conn = get_db_connection()
            with conn.session as session:
                session.execute(text('TRUNCATE TABLE "JCSalesKey";'))
                session.commit()
            df[cols_to_load].to_sql("JCSalesKey", conn.engine, if_exists='append', index=False)
            set_last_upload_time("JCSalesKey")
            st.success(f"JC Sales Key replaced with {len(df)} rows.")
            time.sleep(1)
            st.rerun() 
        except Exception as e:
            st.error(f"Error updating JC Sales Key: {e}")

st.divider()
st.subheader(f"📊 Manage Item Sales Data ({selected_store})")
st.caption(f"Target: `{SALES_TABLE}` - Upload new weekly sales or delete existing dates.")

col_upload, col_delete = st.columns(2)

with col_upload:
    st.markdown("**1. Upload Weekly Sales**")
    sales_date = st.date_input("Week Ending Date", datetime.today())
    sales_file = st.file_uploader("Upload itemsales.csv", type=["csv"], key="sales_upload")
    if sales_file and st.button("Save Sales to DB", type="primary"):
        try:
            sales_df = pd.read_csv(sales_file, dtype=str)
            if not {"UPC", "Item", "# of Items", "Sales $"}.issubset(sales_df.columns): st.error(f"CSV missing columns. Found: {list(sales_df.columns)}")
            else:
                db_rows = pd.DataFrame()
                db_rows["week_date"] = [sales_date] * len(sales_df)
                db_rows["UPC"] = sales_df["UPC"]
                db_rows["Item"] = sales_df["Item"]
                db_rows["qty_sold"] = pd.to_numeric(sales_df["# of Items"], errors='coerce').fillna(0)
                db_rows["Sales_Dollars"] = pd.to_numeric(sales_df["Sales $"].astype(str).str.replace('$','').str.replace(',',''), errors='coerce').fillna(0)
                
                conn = get_db_connection()
                db_rows.to_sql(SALES_TABLE, conn.engine, if_exists='append', index=False)
                st.success(f"✅ Added {len(db_rows)} records to {SALES_TABLE}!")
                time.sleep(1.5)
                st.rerun() 
        except Exception as e:
            st.error(f"Failed to process sales file: {e}")

with col_delete:
    st.markdown("**2. Delete Sales Data**")
    def fetch_sales_dates(table_name):
        try:
            conn = get_db_connection()
            df = conn.query(f'SELECT DISTINCT "week_date" FROM "{table_name}" WHERE "week_date" IS NOT NULL ORDER BY "week_date" DESC', ttl=0)
            if not df.empty: return pd.to_datetime(df["week_date"]).dt.strftime('%Y-%m-%d').unique().tolist()
        except: pass
        return []

    available_dates = fetch_sales_dates(SALES_TABLE)
    if available_dates:
        date_to_delete = st.selectbox("Select Date to Delete", available_dates)
        st.write("") 
        if st.button(f"Delete Sales for {date_to_delete}", type="primary"):
            try:
                conn = get_db_connection()
                with conn.session as session:
                    session.execute(text(f'DELETE FROM "{SALES_TABLE}" WHERE "week_date" = :d'), {"d": date_to_delete})
                    session.commit()
                st.success(f"✅ Successfully deleted all sales data for {date_to_delete} from {selected_store}!")
                time.sleep(1.5)
                st.rerun() 
            except Exception as e:
                st.error(f"Error deleting data: {e}")
    else:
        st.info(f"No item sales dates found in the database for {selected_store}.")
