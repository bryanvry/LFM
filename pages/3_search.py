import streamlit as st
import pandas as pd
from st_keyup import st_keyup
from utils.db import get_db_connection
from utils.helpers import _norm_upc_12, render_top_nav

st.set_page_config(page_title="Search | LFM", layout="wide", initial_sidebar_state="collapsed")

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

render_top_nav()

selected_store = st.session_state["selected_store"]

@st.cache_data(ttl=300, show_spinner=False)
def get_full_search_data(store):
    conn = get_db_connection()
    pb_table = "PricebookTwain" if store == "Twain" else "PricebookRancho"
    sales_table = "salestwain1" if store == "Twain" else "salesrancho1"

    pb_df = conn.query(f'SELECT "Upc", "Name", "size", "cost_cents", "cost_qty", "cents" FROM "{pb_table}"', ttl=300)
    if pb_df.empty: return pd.DataFrame(), []

    pb_df["UPC"] = pb_df["Upc"].astype(str).str.replace('=', '').str.replace('"', '').str.strip()
    pb_df["Item Name"] = pb_df["Name"]
    pb_df["Size"] = pb_df["size"]
    
    safe_cost_qty = pd.to_numeric(pb_df["cost_qty"], errors="coerce").fillna(1).replace(0, 1)
    cost_cents = pd.to_numeric(pb_df["cost_cents"], errors="coerce").fillna(0)
    pb_df["Cost"] = (cost_cents / safe_cost_qty) / 100.0
    pb_df["Price"] = pd.to_numeric(pb_df["cents"], errors="coerce").fillna(0) / 100.0
    
    base_display = pb_df[["UPC", "Item Name", "Size", "Cost", "Price"]].copy()
    base_display["_norm_upc"] = base_display["UPC"].apply(_norm_upc_12)
    
    dates_query = f'SELECT DISTINCT week_date FROM "{sales_table}" WHERE week_date IS NOT NULL ORDER BY week_date DESC LIMIT 15'
    dates_df = conn.query(dates_query, ttl=300)
    
    sales_cols = []
    if not dates_df.empty:
        dates_df["week_date"] = pd.to_datetime(dates_df["week_date"], errors="coerce")
        clean_dates = dates_df.dropna(subset=["week_date"])
        
        if not clean_dates.empty:
            cutoff_date = clean_dates["week_date"].min().strftime('%Y-%m-%d')
            sales_query = f'SELECT "UPC", "week_date", "qty_sold" FROM "{sales_table}" WHERE "week_date" >= \'{cutoff_date}\''
            sales_hist = conn.query(sales_query, ttl=300)
            
            if not sales_hist.empty:
                sales_hist["_upc_norm"] = sales_hist["UPC"].astype(str).apply(_norm_upc_12)
                sales_hist["week_date"] = pd.to_datetime(sales_hist["week_date"]).dt.strftime('%Y-%m-%d')
                
                sales_pivot = sales_hist.pivot_table(index="_upc_norm", columns="week_date", values="qty_sold", aggfunc="sum").fillna(0)
                sales_cols = sorted(sales_pivot.columns, key=lambda x: str(x), reverse=False)
                sales_pivot = sales_pivot[sales_cols]
                
                base_display = base_display.merge(sales_pivot, left_on="_norm_upc", right_index=True, how="left")
    
    base_display = base_display.drop(columns=["_norm_upc"])
    for c in sales_cols:
        if c in base_display.columns:
            base_display[c] = base_display[c].fillna(0).astype(int)
            
    return base_display, sales_cols

st.header(f"Live Pricebook Search: {selected_store}")

full_db, available_sales_cols = get_full_search_data(selected_store)
max_available_weeks = len(available_sales_cols) if available_sales_cols else 1

col_search, col_weeks = st.columns([3, 1])

with col_search:
    search_query = st_keyup("Search by UPC or Item Name", placeholder="Start typing...", key="live_search")
    
with col_weeks:
    num_weeks = st.number_input("Sales Weeks to Show", min_value=1, max_value=max_available_weeks, value=min(15, max_available_weeks))

if search_query:
    safe_query = str(search_query).lower()
    filtered_df = full_db[full_db["UPC"].str.lower().str.contains(safe_query, na=False) | full_db["Item Name"].str.lower().str.contains(safe_query, na=False)]
    
    if filtered_df.empty: st.warning("No items found.")
    else:
        cols_to_show = ["UPC", "Item Name", "Size", "Cost", "Price"]
        if available_sales_cols: cols_to_show.extend(available_sales_cols[-num_weeks:])
        display_df = filtered_df[cols_to_show]
        st.success(f"Found {len(display_df)} items.")
        st.dataframe(display_df, column_config={"UPC": st.column_config.TextColumn("UPC"), "Item Name": st.column_config.TextColumn("Item Name"), "Size": st.column_config.TextColumn("Size"), "Cost": st.column_config.NumberColumn("Unit Cost", format="$%.2f"), "Price": st.column_config.NumberColumn("Retail Price", format="$%.2f")}, hide_index=True, use_container_width=True)
