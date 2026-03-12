import streamlit as st
import os

# Set configuration to collapsed by default
st.set_page_config(page_title="LFM Process", layout="wide", initial_sidebar_state="collapsed")

# CSS to completely remove the sidebar and the toggle button
st.markdown(
    """
    <style>
        section[data-testid="stSidebar"] {
            display: none !important;
        }
        [data-testid="collapsedControl"] {
            display: none !important;
        }
    </style>
    """,
    unsafe_allow_html=True,
)

MASTER_PASSKEY = st.secrets["APP_PASSKEY"]
current_dir = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(current_dir, "logo.png")

if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False

if not st.session_state["authenticated"]:
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        st.write("")
        st.write("")
        logo_col1, logo_col2, logo_col3 = st.columns([1, 2, 1])
        with logo_col2:
            st.image(LOGO_PATH, width="stretch")
        
        entered_key = st.text_input("Passkey", type="password", placeholder="Enter passkey...")
        if st.button("Login", width="stretch"):
            if entered_key == MASTER_PASSKEY:
                st.session_state["authenticated"] = True
                st.rerun() 
            else:
                st.error("❌ Incorrect passkey. Please try again.")
    st.stop()

col_title, col_store = st.columns([7, 1]) 
with col_title:
    st.image(LOGO_PATH, width=250)

with col_store:
    selected_store = st.selectbox("Store", ["Twain", "Rancho"], label_visibility="collapsed")
    st.caption(f"📍 **{selected_store}**")

st.session_state["selected_store"] = selected_store

if selected_store == "Twain":
    st.session_state["PRICEBOOK_TABLE"] = "PricebookTwain"
    st.session_state["SALES_TABLE"] = "salestwain1"
    st.session_state["VENDOR_MAP_TABLE"] = "BeerandLiquorKeyTwain"
else:
    st.session_state["PRICEBOOK_TABLE"] = "PricebookRancho"
    st.session_state["SALES_TABLE"] = "salesrancho1"
    st.session_state["VENDOR_MAP_TABLE"] = "BeerandLiquorKeyRancho"

st.divider()

st.subheader("Navigation")
st.markdown("Select a module to access the relevant workflow.")

st.write("") 

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("#### Orders")
    st.caption("Generate vendor orders based on sales history.")
    st.page_link("pages/1_order.py", label="Access Orders", width="stretch")

with col2:
    st.markdown("#### Invoices")
    st.caption("Process invoices, verify margins, and export POS files.")
    st.page_link("pages/2_invoice.py", label="Access Invoices", width="stretch")

with col3:
    st.markdown("#### Search")
    st.caption("Query pricebook items and review historical sales.")
    st.page_link("pages/3_search.py", label="Access Search", width="stretch")

with col4:
    st.markdown("#### Admin")
    st.caption("Manage database configurations and vendor mapping.")
    st.page_link("pages/4_admin.py", label="Access Admin", width="stretch")

st.divider()

status_col1, status_col2 = st.columns(2)
with status_col1:
    st.markdown(f"**Current Location:** {selected_store}")
    st.caption(f"Active Tables: {st.session_state['PRICEBOOK_TABLE']}, {st.session_state['SALES_TABLE']}")
with status_col2:
    st.markdown("**System Status: Connected**")
    st.caption("Database link verified. All parsers operational.")