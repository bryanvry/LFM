import streamlit as st
import os

st.set_page_config(page_title="LFM Process", page_icon="🧾", layout="wide")

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
            st.image(LOGO_PATH, use_column_width=True)
        
        entered_key = st.text_input("Passkey", type="password", placeholder="Enter passkey...")
        if st.button("Login", use_container_width=True):
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

st.info("👈 Please select a tool from the sidebar menu to begin.")
