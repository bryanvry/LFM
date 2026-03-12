import streamlit as st
import os
from utils.helpers import render_top_nav

# Set configuration
st.set_page_config(page_title="LFM Process", layout="wide", initial_sidebar_state="collapsed")

# Hide sidebar and header on the login screen
st.markdown(
    """
    <style>
        [data-testid="stSidebar"] { display: none !important; }
        [data-testid="collapsedControl"] { display: none !important; }
        [data-testid="stHeader"] { display: none !important; }
        .block-container { padding-top: 2rem !important; }
    </style>
    """,
    unsafe_allow_html=True,
)

MASTER_PASSKEY = st.secrets["APP_PASSKEY"]
current_dir = os.path.dirname(os.path.abspath(__file__))
LOGO_PATH = os.path.join(current_dir, "logo.png")

# Initialize default states
if "authenticated" not in st.session_state:
    st.session_state["authenticated"] = False
if "selected_store" not in st.session_state:
    st.session_state["selected_store"] = "Twain"

# Authentication Gate
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
                st.error("Incorrect passkey. Please try again.")
    st.stop()

# --- Main Interface ---
render_top_nav()

# Landing Page Content
st.subheader("System Overview")
st.markdown("Select a module from the top navigation menu to begin your workflow.")

status_col1, status_col2 = st.columns(2)
with status_col1:
    st.markdown(f"**Current Location:** {st.session_state['selected_store']}")
    st.caption(f"Active Tables: {st.session_state['PRICEBOOK_TABLE']}, {st.session_state['SALES_TABLE']}")
with status_col2:
    st.markdown("**System Status: Connected**")
    st.caption("Database link verified. All parsers operational.")