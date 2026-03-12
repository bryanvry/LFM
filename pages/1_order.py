import streamlit as st
import pandas as pd
from datetime import datetime, timedelta
from utils.db import get_db_connection, load_pricebook
from utils.helpers import _norm_upc_12, to_xlsx_bytes

if not st.session_state.get("authenticated", False):
    st.info("Please login from the main page.")
    st.stop()

selected_store = st.session_state["selected_store"]
PRICEBOOK_TABLE = st.session_state["PRICEBOOK_TABLE"]
SALES_TABLE = st.session_state["SALES_TABLE"]
VENDOR_MAP_TABLE = st.session_state["VENDOR_MAP_TABLE"]

st.header(f"Orders: {selected_store}")

# --- Interactive Order Builder ---
st.subheader("Build Order")

try:
    conn = get_db_connection()
    companies_df = conn.query(f'SELECT DISTINCT "Company" FROM "{VENDOR_MAP_TABLE}"', ttl=0)
    
    if not companies_df.empty:
        company_options = sorted([str(c) for c in companies_df["Company"].unique() if c is not None and str(c).strip() != 'nan'])
    else:
        company_options = ["Breakthru", "Southern Glazer's", "Nevada Beverage"]
    
    target_company = st.selectbox("Select Company", company_options)
    
    if st.button(f"Load {target_company} Items"):
        map_query = f'SELECT * FROM "{VENDOR_MAP_TABLE}" WHERE "Company" = :company_name'
        vendor_df = conn.query(map_query, params={"company_name": target_company}, ttl=0)

        if vendor_df.empty:
            st.warning(f"No items found for {target_company}.")
            st.session_state['order_df'] = None
        else:
            vendor_df["_key_norm"] = vendor_df["Full Barcode"].astype(str).apply(_norm_upc_12)
            pb_df = load_pricebook(PRICEBOOK_TABLE)
            start_date = datetime.today() - timedelta(weeks=24) 
            
            sales_query = f'SELECT "UPC", "week_date", "qty_sold" FROM "{SALES_TABLE}" WHERE "week_date" >= :start_date'
            sales_hist = conn.query(sales_query, params={"start_date": start_date.strftime('%Y-%m-%d')}, ttl=0)
            
            merged = vendor_df.merge(pb_df, left_on="_key_norm", right_on="_norm_upc", how="left")
            if "Name_x" in merged.columns: merged = merged.rename(columns={"Name_x": "Name"})
            elif "Name_y" in merged.columns and "Name" not in merged.columns: merged = merged.rename(columns={"Name_y": "Name"})
            
            sales_cols_display = []
            if not sales_hist.empty:
                sales_hist["_upc_norm"] = sales_hist["UPC"].astype(str).apply(_norm_upc_12)
                sales_hist["week_date"] = pd.to_datetime(sales_hist["week_date"]).dt.strftime('%Y-%m-%d')
                
                sales_pivot = sales_hist.pivot_table(index="_upc_norm", columns="week_date", values="qty_sold", aggfunc="sum").fillna(0)
                sorted_dates = sorted(sales_pivot.columns, key=lambda x: str(x), reverse=False)
                sales_cols = sorted_dates[-15:]
                sales_pivot = sales_pivot[sales_cols]
                
                rename_dict = {col: pd.to_datetime(col).strftime('%m/%d') for col in sales_cols}
                sales_pivot = sales_pivot.rename(columns=rename_dict)
                sales_cols_display = list(rename_dict.values())
                
                merged = merged.merge(sales_pivot, left_on="_key_norm", right_index=True, how="left")

            if "setstock" in merged.columns:
                clean_stock = merged["setstock"].astype(str).str.replace('=', '').str.replace('"', '').str.strip()
                merged["Stock"] = pd.to_numeric(clean_stock, errors='coerce').fillna(0)
            else: merged["Stock"] = 0
            
            merged["Order"] = 0
            
            base_cols = ["Full Barcode", "type", "Name", "Size", "PACK"]
            available_base = [c for c in base_cols if c in merged.columns]
            
            final_cols = available_base + sales_cols_display + ["Stock", "Order"]
            final_merged = merged[final_cols].copy()
            
            final_merged["_sort_name"] = final_merged["Name"].astype(str).str.strip().str.lower()
            if "type" in final_merged.columns:
                final_merged["type"] = final_merged["type"].fillna("Z_Other") 
                final_merged = final_merged.sort_values(by=["type", "_sort_name"], ascending=[True, True])
                final_merged["type"] = final_merged["type"].replace("Z_Other", "") 
            else:
                final_merged = final_merged.sort_values(by="_sort_name", ascending=True)
                
            final_merged = final_merged.drop(columns=["_sort_name"])
            
            st.session_state['order_df'] = final_merged
            st.session_state['active_company'] = target_company
            st.session_state['sales_cols_display'] = sales_cols_display 

except Exception as e:
    st.error(f"System Error: {e}")

if 'order_df' in st.session_state and st.session_state['order_df'] is not None:
    st.divider()
    st.write(f"**Building Order for: {st.session_state.get('active_company')}**")
    
    all_columns = st.session_state['order_df'].columns.tolist()
    locked_columns = [col for col in all_columns if col != "Order"]
    
    col_configs = {
        "Order": st.column_config.NumberColumn("Order Qty", help="Enter cases to order", min_value=0, step=1, required=True),
        "Name": st.column_config.TextColumn("Name", width="large"),
        "Size": st.column_config.TextColumn("Size", width="small"),
        "PACK": st.column_config.NumberColumn("Pack", width="small"),
        "Stock": st.column_config.NumberColumn("Stock", width="small")
    }
    
    for sc in st.session_state.get('sales_cols_display', []):
        col_configs[sc] = st.column_config.NumberColumn(sc, width="small")
        
    if "type" in all_columns: col_configs["type"] = None 
    
    edited_df = st.data_editor(
        st.session_state['order_df'],
        use_container_width=True,
        height=600,
        disabled=locked_columns,
        column_config=col_configs, 
        hide_index=True
    )
    
    if st.button("Finish & Download Order"):
        final_order = edited_df[edited_df["Order"] > 0].copy()
        
        if final_order.empty:
            st.warning("No items ordered (Order Qty is 0 for all rows).")
        else:
            final_order["_sort_name"] = final_order["Name"].astype(str).str.strip().str.lower()
            if "type" in final_order.columns:
                final_order["type"] = final_order["type"].replace("", "Z_Other")
                final_order = final_order.sort_values(by=["type", "_sort_name"], ascending=[True, True])
                final_order["type"] = final_order["type"].replace("Z_Other", "")
            else:
                final_order = final_order.sort_values(by="_sort_name", ascending=True)
                
            final_order = final_order.drop(columns=["_sort_name"])
            
            output_cols = ["type", "Name", "Size", "Order"]
            valid_cols = [c for c in output_cols if c in final_order.columns]
            download_df = final_order[valid_cols]
            
            st.download_button(
                label=f"⬇️ Download {st.session_state['active_company']} Order",
                data=to_xlsx_bytes({st.session_state['active_company']: download_df}),
                file_name=f"ORDER_{st.session_state['active_company']}_{datetime.today().strftime('%Y-%m-%d')}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
            )
            st.success(f"Ready! Contains {len(download_df)} items.")
