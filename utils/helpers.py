import pandas as pd
from io import BytesIO
import xlsxwriter
import barcode
from barcode.writer import ImageWriter

def _norm_upc_12(u) -> str:
    if pd.isna(u): return ""
    s = str(u).strip()
    s = "".join(ch for ch in s if ch.isdigit())
    if not s: return ""
    while len(s) > 13 and s.startswith("0"): s = s[1:]
    if len(s) == 13 and s.startswith("0"): s = s[1:]
    if len(s) > 13: s = s[-13:]
    if len(s) < 12: s = s.zfill(12)
    return s

def to_csv_bytes(df):
    return df.to_csv(index=False).encode('utf-8')

def to_xlsx_bytes(dfs_dict):
    output = BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        for sheet_name, df in dfs_dict.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)
    output.seek(0)
    return output.getvalue()

def generate_barcode_excel(df):
    output = BytesIO()
    workbook = xlsxwriter.Workbook(output, {'in_memory': True})
    worksheet = workbook.add_worksheet('New Prices')
    headers = ["UPC", "Brand", "Description", "Now", "New", "Barcode"]
    for col_num, header in enumerate(headers): worksheet.write(0, col_num, header)
    EAN = barcode.get_barcode_class('ean13')
    for row_num, (index, row) in enumerate(df.iterrows(), 1):
        worksheet.write(row_num, 0, str(row['UPC']))
        worksheet.write(row_num, 1, str(row['Brand']))
        worksheet.write(row_num, 2, str(row['Description']))
        worksheet.write(row_num, 3, f"${row['Now']:.2f}" if pd.notna(row['Now']) else "")
        worksheet.write(row_num, 4, f"${row['New']:.2f}")
        clean_upc = "".join(filter(str.isdigit, str(row['UPC']))).zfill(12)
        ean_str = "0" + clean_upc
        try:
            ean_img = EAN(ean_str, writer=ImageWriter())
            img_io = BytesIO()
            ean_img.write(img_io, options={"write_text": False, "module_height": 8.0, "quiet_zone": 2.0})
            img_io.seek(0)
            worksheet.insert_image(row_num, 5, 'barcode.png', {'image_data': img_io, 'x_scale': 0.4, 'y_scale': 0.4, 'positioning': 1})
            worksheet.set_row(row_num, 35)
        except Exception:
            worksheet.write(row_num, 5, "Error generating")
    worksheet.set_column('A:A', 15)
    worksheet.set_column('C:C', 40)
    worksheet.set_column('F:F', 30)
    workbook.close()
    output.seek(0)
    return output.getvalue()
import streamlit as st

def render_top_nav():
    # 1. Adjust top padding for all sub-pages
    st.markdown(
        """
        <style>
            [data-testid="stSidebar"] { display: none !important; }
            [data-testid="collapsedControl"] { display: none !important; }
            [data-testid="stHeader"] { display: none !important; }
            .block-container { padding-top: 2rem; }
        </style>
        """,
        unsafe_allow_html=True,
    )

    # 2. Setup the top bar grid
    col1, col2, col3, col4, col5, col6 = st.columns([1, 1, 1, 1, 1, 1.5])

    with col1: st.page_link("app.py", label="Home")
    with col2: st.page_link("pages/1_order.py", label="Orders")
    with col3: st.page_link("pages/2_invoice.py", label="Invoices")
    with col4: st.page_link("pages/3_search.py", label="Search")
    with col5: st.page_link("pages/4_admin.py", label="Admin")
    
    with col6:
        # 3. Persistent Store Selector
        current_store = st.session_state.get("selected_store", "Twain")
        store_index = 0 if current_store == "Twain" else 1
        
        selected_store = st.selectbox(
            "Location", 
            ["Twain", "Rancho"], 
            index=store_index,
            label_visibility="collapsed",
            key="global_store"
        )

        # Update session state and refresh if changed
        if selected_store != current_store:
            st.session_state["selected_store"] = selected_store
            st.rerun()

    # 4. Route Tables based on the selected store
    if st.session_state.get("selected_store") == "Twain":
        st.session_state["PRICEBOOK_TABLE"] = "PricebookTwain"
        st.session_state["SALES_TABLE"] = "salestwain1"
        st.session_state["VENDOR_MAP_TABLE"] = "BeerandLiquorKeyTwain"
    else:
        st.session_state["PRICEBOOK_TABLE"] = "PricebookRancho"
        st.session_state["SALES_TABLE"] = "salesrancho1"
        st.session_state["VENDOR_MAP_TABLE"] = "BeerandLiquorKeyRancho"
        

    st.divider()

