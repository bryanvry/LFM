import streamlit as st
import pandas as pd
import numpy as np
import time
import re
from datetime import datetime
from utils.db import get_db_connection, log_activity, load_pricebook, load_vendor_map, load_jcsales_key
from utils.helpers import _norm_upc_12, to_csv_bytes, generate_barcode_excel, to_xlsx_bytes, render_top_nav
from parsers import SouthernGlazersParser, NevadaBeverageParser, BreakthruParser, JCSalesParser, UnifiedParser, CostcoParser
from sqlalchemy import text

st.set_page_config(page_title="Invoices | LFM", layout="wide", initial_sidebar_state="collapsed")

if not st.session_state.get("authenticated", False):
    st.switch_page("app.py")

render_top_nav()

selected_store = st.session_state["selected_store"]
PRICEBOOK_TABLE = st.session_state["PRICEBOOK_TABLE"]
SALES_TABLE = st.session_state["SALES_TABLE"]
VENDOR_MAP_TABLE = st.session_state["VENDOR_MAP_TABLE"]

st.header(f"Invoice Processing: {selected_store}")

vendor_options = ["Unified", "JC Sales", "Southern Glazer's", "Nevada Beverage", "Breakthru", "Costco"]
vendor = st.selectbox("Select Vendor", vendor_options)

# --- UNIFIED / JC SALES ---
if vendor == "Unified":
    st.info(f"Processing against **{PRICEBOOK_TABLE}**")
    if st.session_state.get("current_un_vendor") != vendor:
        st.session_state["analyze_unified"] = False
        st.session_state["current_un_vendor"] = vendor
        if "unified_final_df" in st.session_state: del st.session_state["unified_final_df"]
            
    inv_dfs = []
    up_files = st.file_uploader("Upload Unified Invoice(s)", type=["csv", "xlsx", "xls"], accept_multiple_files=True, key="un_files")
    
    if not up_files: st.session_state["analyze_unified"] = False
        
    if st.button("Process Unified"):
        st.session_state["analyze_unified"] = True
        if "unified_final_df" in st.session_state: del st.session_state["unified_final_df"]
            
    if st.session_state.get("analyze_unified", False) and up_files:
        for f in up_files:
            try:
                f.seek(0)
                inv_dfs.append(UnifiedParser().parse(f))
            except Exception as e:
                st.error(f"Error parsing {f.name}: {e}")

    if inv_dfs:
        pb_df = load_pricebook(PRICEBOOK_TABLE)
        if pb_df.empty:
            st.error("Pricebook is empty. Please upload one in Admin tab.")
            st.stop()

        full_inv = pd.concat(inv_dfs, ignore_index=True)
        if "invoice_date" in full_inv.columns:
            full_inv["invoice_date"] = pd.to_datetime(full_inv["invoice_date"], errors='coerce')
            full_inv = full_inv.sort_values("invoice_date", ascending=True).drop_duplicates(subset=["UPC"], keep="last")
        
        full_inv["_norm_upc"] = full_inv["UPC"].astype(str).apply(_norm_upc_12)
        merged = full_inv.merge(pb_df, on="_norm_upc", how="left")
        
        merged["New_Cost_Cents"] = (pd.to_numeric(merged["+Cost"], errors='coerce') * 100).fillna(0).astype(int)
        merged["New_Pack"] = pd.to_numeric(merged["Pack"], errors='coerce').fillna(1).astype(int)
        merged["cost_cents"] = pd.to_numeric(merged["cost_cents"], errors='coerce').fillna(0).astype(int)
        merged["cost_qty"] = pd.to_numeric(merged["cost_qty"], errors='coerce').fillna(1).astype(int)
        merged["cents"] = pd.to_numeric(merged["cents"], errors='coerce').fillna(0).astype(int) 
        
        matched = merged[merged["Upc"].notna()].copy()
        unmatched = merged[merged["Upc"].isna()].copy()
        
        changes_count = 0
        if not matched.empty:
             matched["Old_Unit_Cents"] = matched["cost_cents"] / matched["cost_qty"].replace(0, 1)
             matched["New_Unit_Cents"] = matched["New_Cost_Cents"] / matched["New_Pack"].replace(0, 1)
             matched["Cost_Changed"] = abs(matched["New_Unit_Cents"] - matched["Old_Unit_Cents"]) > 1.0
             changes_count = matched["Cost_Changed"].sum()

        log_activity(selected_store, vendor, len(full_inv), changes_count)

        if not matched.empty:
            st.divider()
            st.subheader("📊 Invoice Item Details & Retail Calculator")
            margin_divisor = 0.7 if selected_store == "Rancho" else 0.6
            margin_label = "30%" if selected_store == "Rancho" else "40%"
            
            def calc_row_metrics(row):
                case_cost = row["+Cost"] if pd.notna(row["+Cost"]) else 0.0
                pack = row["New_Pack"] if row["New_Pack"] > 0 else 1
                unit_cost = case_cost / pack
                target_retail = max(0, np.ceil((unit_cost / margin_divisor) * 10) / 10.0 - 0.01)
                retail_str = f"${target_retail:.2f}" + (" *" if row["Cost_Changed"] else "")
                return unit_cost, retail_str

            metrics = matched.apply(calc_row_metrics, axis=1, result_type='expand')
            matched["Unit Cost"] = metrics[0]
            matched["Retail String"] = metrics[1]
            matched["Now"] = matched["cents"] / 100.0
            matched["New"] = None
            
            final_view = matched[["UPC", "Brand", "Description", "Cost", "+Cost", "Unit Cost", "Now", "Retail String", "New"]].rename(
                columns={"+Cost": "Net Cost", "Unit Cost": "Unit", "Retail String": "Retail"}
            )
            
            st.write("**Edit the 'New' column to set a custom retail price.**")
            edited_df = st.data_editor(
                final_view,
                column_config={
                    "UPC": st.column_config.TextColumn(disabled=True),
                    "Brand": st.column_config.TextColumn(disabled=True),
                    "Description": st.column_config.TextColumn(disabled=True),
                    "Cost": st.column_config.NumberColumn("Cost ($)", format="$%.2f", disabled=True),
                    "Net Cost": st.column_config.NumberColumn("Net Cost ($)", format="$%.2f", disabled=True),
                    "Unit": st.column_config.NumberColumn(format="$%.2f", disabled=True),
                    "Now": st.column_config.NumberColumn(format="$%.2f", help="Current Pricebook Price", disabled=True),
                    "Retail": st.column_config.TextColumn(help=f"Calculated Retail ({margin_label} Margin). * indicates cost change.", disabled=True),
                    "New": st.column_config.NumberColumn("New ($)", format="$%.2f", min_value=0.0)
                },
                use_container_width=True, hide_index=True, height=450
            )

            changes = matched[matched["Cost_Changed"]].copy()
            if not changes.empty:
                st.error(f"{len(changes)} Unit Price Changes Detected")
                st.dataframe(pd.DataFrame({
                    "UPC": changes["Upc"], "Brand": changes["Brand"], "Description": changes["Description"],
                    "Old Unit Cost": changes["Old_Unit_Cents"] / 100.0, "New Unit Cost": changes["New_Unit_Cents"] / 100.0,
                    "Old Case": changes["cost_cents"] / 100.0, "New Case": changes["New_Cost_Cents"] / 100.0
                }), column_config={"Old Unit Cost": st.column_config.NumberColumn(format="$%.2f"), "New Unit Cost": st.column_config.NumberColumn(format="$%.2f"), "Old Case": st.column_config.NumberColumn(format="$%.2f"), "New Case": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True)

            st.divider()
            st.subheader("Generate Export Files")
            if st.button("Confirm Prices & Generate Files", type="primary"):
                st.session_state["unified_final_df"] = edited_df
                st.session_state["unified_matched_df"] = matched
            
            if "unified_final_df" in st.session_state and "unified_matched_df" in st.session_state:
                st.success("Files prepared successfully! Ready for download.")
                final_edited = st.session_state["unified_final_df"]
                final_matched = st.session_state["unified_matched_df"]
                final_matched["User_New_Price"] = final_edited["New"].values
            
                pos_out = pd.DataFrame()
                pos_out["Upc"] = final_matched["Upc"].apply(lambda u: f'="{str(u).replace("=", "").replace("\"", "").strip()}"')
                pos_out["cost_cents"] = final_matched["New_Cost_Cents"]
                pos_out["cost_qty"] = final_matched["New_Pack"]
                
                qty_col = next((c for c in final_matched.columns if c in ["Case Qty", "Case Quantity", "Cases", "Qty"]), None)
                total_actual_cases = 0
                if qty_col:
                    cases = pd.to_numeric(final_matched[qty_col], errors='coerce').fillna(0)
                    pos_out["addstock"] = (cases * pos_out["cost_qty"]).astype(int)
                    total_actual_cases = int(cases.sum())
                else: pos_out["addstock"] = 0
                
                for col in ["Department", "qty", "cents", "incltaxes", "inclfees", "ebt", "byweight", "Fee Multiplier", "size", "Name"]:
                    if col == "cents":
                        base_cents = pd.to_numeric(final_matched["cents"], errors='coerce').fillna(0).astype(int)
                        mask = final_matched["User_New_Price"].notna()
                        base_cents[mask] = (final_matched.loc[mask, "User_New_Price"] * 100).astype(int)
                        pos_out["cents"] = base_cents
                    elif col in final_matched.columns: pos_out[col] = final_matched[col]
                    else: pos_out[col] = ""

                final_pos_out = pos_out[["Upc", "Department", "qty", "cents", "incltaxes", "inclfees", "Name", "size", "ebt", "byweight", "Fee Multiplier", "cost_qty", "cost_cents", "addstock"]].copy()
                num_price_updates = (final_matched["User_New_Price"] > 0).sum() if "User_New_Price" in final_matched.columns else 0
                st.caption(f"Ready to update stock for {len(final_pos_out)} items and update price for {num_price_updates} items (Total Cases: {total_actual_cases})")
                
                dl_col1, dl_col2 = st.columns(2)
                with dl_col1: st.download_button("⬇️ Download POS Update CSV", to_csv_bytes(final_pos_out), f"POS_Update_{vendor}_{datetime.today().strftime('%Y-%m-%d')}.csv", "text/csv", use_container_width=True)
                with dl_col2:
                    edited_items_only = final_edited[final_edited["New"].notna() & (final_edited["New"] > 0)].copy()
                    if not edited_items_only.empty: st.download_button("🏷️ Download Price Labels (Excel)", data=generate_barcode_excel(edited_items_only), file_name=f"Price_Labels_{datetime.today().strftime('%Y-%m-%d')}.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", use_container_width=True)
                    else: st.button("🏷️ Download Price Labels (Excel)", disabled=True, use_container_width=True)
        
        if not unmatched.empty:
            st.warning(f"{len(unmatched)} items not found in Pricebook.")
            margin_divisor = 0.7 if selected_store == "Rancho" else 0.6
            def calc_unmatched_retail(row):
                unit_cost = (row["+Cost"] if pd.notna(row["+Cost"]) else 0.0) / (row["New_Pack"] if row["New_Pack"] > 0 else 1)
                return unit_cost, max(0, np.ceil((unit_cost / margin_divisor) * 10) / 10.0 - 0.01)

            metrics = unmatched.apply(calc_unmatched_retail, axis=1, result_type='expand')
            disp_unmatched = unmatched[["UPC", "Brand", "Description", "+Cost", "New_Pack"]].copy()
            disp_unmatched["Unit"] = metrics[0]
            disp_unmatched["Retail"] = metrics[1]
            disp_unmatched = disp_unmatched.rename(columns={"+Cost": "Case Cost", "New_Pack": "Pack"})
            
            st.dataframe(disp_unmatched, column_config={"Case Cost": st.column_config.NumberColumn(format="$%.2f"), "Unit": st.column_config.NumberColumn(format="$%.2f"), "Retail": st.column_config.NumberColumn(format="$%.2f")}, hide_index=True, use_container_width=True)

# --- JC SALES ---
elif vendor == "JC Sales":
    st.info(f"Using Global **JCSalesKey** + **{PRICEBOOK_TABLE}**")
    if st.session_state.get("current_jc_vendor") != vendor:
        st.session_state["analyze_jc"] = False
        st.session_state["current_jc_vendor"] = vendor
        
    jc_text = st.text_area("Paste JC Sales Text (Select All in PDF -> Copy -> Paste)", height=250)
    if not jc_text: st.session_state["analyze_jc"] = False
    if st.button("Analyze JC Sales", type="primary"): st.session_state["analyze_jc"] = True
        
    if st.session_state.get("analyze_jc", False) and jc_text:
        jc_key = load_jcsales_key()
        pb_df = load_pricebook(PRICEBOOK_TABLE)
        if jc_key.empty:
            st.error("JCSalesKey is empty. Please upload it in the Admin tab.")
            st.stop()
            
        jc_df, _ = JCSalesParser().parse(jc_text)
        if jc_df.empty:
            st.error("No items parsed from text.")
            st.stop()
            
        jc_df["ITEM_str"] = jc_df["ITEM"].astype(str).str.strip()
        jc_key["ITEM_str"] = jc_key["ITEM"].astype(str).str.strip()

        pb_upcs = set(pb_df["_norm_upc"])
        pb_names = dict(zip(pb_df["_norm_upc"], pb_df["Name"]))
        missing_items_list = jc_df[~jc_df["ITEM_str"].isin(jc_key["ITEM_str"])]["ITEM_str"].unique()
        
        db_matched_pre = jc_df[jc_df["ITEM_str"].isin(jc_key["ITEM_str"])].copy()
        pre_mapped = db_matched_pre.merge(jc_key, on="ITEM_str", how="left")
        
        def has_valid_upc(row):
            u1, u2 = _norm_upc_12(row.get("UPC1", "")), _norm_upc_12(row.get("UPC2", ""))
            return bool(u1 and u1 in pb_upcs) or bool(u2 and u2 in pb_upcs)
            
        mismatched_items_list = pre_mapped[~pre_mapped.apply(has_valid_upc, axis=1)]["ITEM_str"].unique() if not pre_mapped.empty else []
        if "ignore_scrape" not in st.session_state: st.session_state["ignore_scrape"] = set()
            
        items_to_scrape = [i for i in list(set(list(missing_items_list) + list(mismatched_items_list))) if i not in st.session_state["ignore_scrape"]]
        
        if items_to_scrape:
            scrape_hash = "_".join(sorted(items_to_scrape))
            if st.session_state.get("last_scrape_hash") != scrape_hash:
                st.write(f"### Auto-Scraping {len(items_to_scrape)} Items")
                progress_bar = st.progress(0)
                status_text = st.empty()

                import requests
                from bs4 import BeautifulSoup
                from urllib.parse import urljoin

                potential_matches = []
                headers = {"User-Agent": "Mozilla/5.0"}

                def scrape_jcsales_best_upc(item_num, pb_upcs):
                    item_num_str = re.sub(r"\.0$", "", str(item_num).strip())
                    try:
                        resp = requests.get(f"https://www.jcsalesweb.com/Catalog/Search?query={item_num_str}", headers=headers, timeout=15)
                        if resp.status_code != 200: return None, []
                        soup = BeautifulSoup(resp.text, "html.parser")
                        product_link = None
                        item_label = soup.find(string=re.compile(rf"Item No:\s*{re.escape(item_num_str)}", re.IGNORECASE))
                        if item_label:
                            parent = item_label.parent
                            for _ in range(6):
                                if not parent: break
                                if parent.name == "a" and parent.get("href") and "/Catalog/Product/" in parent["href"]:
                                    product_link = parent["href"]
                                    break
                                link_in_parent = parent.find("a", href=True)
                                if link_in_parent and "/Catalog/Product/" in link_in_parent["href"]:
                                    product_link = link_in_parent["href"]
                                    break
                                parent = parent.parent
                        if not product_link: return None, []
                        prod_resp = requests.get(urljoin("https://www.jcsalesweb.com", product_link), headers=headers, timeout=15)
                        if prod_resp.status_code != 200: return None, []
                        barcodes = []
                        for node in BeautifulSoup(prod_resp.text, "html.parser").find_all(string=re.compile(r"Barcode:", re.IGNORECASE)):
                            clean_text = re.sub(r"^.*?Barcode:\s*", "", node.parent.get_text(" ", strip=True) if node.parent else str(node), flags=re.IGNORECASE).strip()
                            for code in clean_text.split(","):
                                norm = _norm_upc_12(code)
                                if norm and norm not in barcodes: barcodes.append(norm)
                            if barcodes: break
                        if not barcodes: return None, []
                        return next((code for code in barcodes if code in pb_upcs), barcodes[0]), barcodes[:6]
                    except: return None, []

                for i, item_num in enumerate(items_to_scrape):
                    item_num_str = re.sub(r"\.0$", "", str(item_num).strip())
                    status_text.info(f"🔎 Searching {i+1}/{len(items_to_scrape)}: Item **{item_num_str}**...")
                    best_upc, _ = scrape_jcsales_best_upc(item_num_str, pb_upcs)
                    if best_upc:
                        row_match = jc_df[jc_df["ITEM_str"].astype(str).str.strip() == item_num_str]
                        if not row_match.empty:
                            pricebook_name = pb_names.get(best_upc, "⚠️ Not in Pricebook")
                            potential_matches.append({"Confirm": pricebook_name != "⚠️ Not in Pricebook", "ITEM": item_num_str, "Found UPC": best_upc, "Invoice Desc": row_match.iloc[0]["DESCRIPTION"], "Pricebook Name": pricebook_name, "PACK": row_match.iloc[0]["PACK"], "COST": row_match.iloc[0]["COST"]})
                            status_text.success(f"✅ Found UPC for **{item_num_str}**")
                    else: status_text.error(f"❌ No barcodes found for **{item_num_str}**")
                    progress_bar.progress((i + 1) / len(items_to_scrape))
                    time.sleep(1.5)

                status_text.info("✨ Scraping complete! Preparing review board...")
                time.sleep(1)
                st.session_state["scraped_matches"] = potential_matches
                st.session_state["last_scrape_hash"] = scrape_hash
                status_text.empty()
                progress_bar.empty()

            scraped_results = st.session_state.get("scraped_matches", [])
            if scraped_results:
                st.info("🤖 **Auto-Scraper found potential matches!** Review the items below:")
                df_matches = pd.DataFrame(scraped_results)
                edited_matches = st.data_editor(df_matches, column_config={"Confirm": st.column_config.CheckboxColumn("Confirm?", default=True), "ITEM": st.column_config.TextColumn(disabled=True), "Found UPC": st.column_config.TextColumn(disabled=True), "Invoice Desc": st.column_config.TextColumn(disabled=True), "Pricebook Name": st.column_config.TextColumn(disabled=True), "PACK": None, "COST": None}, hide_index=True, key="scraper_review")
                col1, col2 = st.columns(2)
                with col1:
                    if st.button("Save Confirmed Matches", type="primary"):
                        confirmed = edited_matches[edited_matches["Confirm"]]
                        unconfirmed = edited_matches[~edited_matches["Confirm"]]
                        if not unconfirmed.empty: st.session_state["ignore_scrape"].update(unconfirmed["ITEM"].tolist())
                        if not confirmed.empty:
                            new_db_rows, update_db_rows = [], []
                            for _, r in confirmed.iterrows():
                                if r["ITEM"] in jc_key["ITEM_str"].values: update_db_rows.append({"ITEM": r["ITEM"], "UPC1": r["Found UPC"]})
                                else: new_db_rows.append({"ITEM": r["ITEM"], "UPC1": r["Found UPC"], "UPC2": "", "DESCRIPTION": r["Invoice Desc"], "PACK": r["PACK"], "COST": r["COST"]})
                            conn = get_db_connection()
                            with conn.session as session:
                                if new_db_rows: pd.DataFrame(new_db_rows).to_sql("JCSalesKey", conn.engine, if_exists='append', index=False)
                                if update_db_rows:
                                    for r in update_db_rows: session.execute(text('UPDATE "JCSalesKey" SET "UPC1" = :u WHERE "ITEM" = :i'), {"u": r["UPC1"], "i": r["ITEM"]})
                                session.commit()
                        st.session_state.pop("last_scrape_hash", None)
                        st.session_state.pop("scraped_matches", None)
                        st.success("Matches Saved! Re-analyzing...")
                        st.rerun()
                with col2:
                    if st.button("Discard All & Map Manually"):
                        st.session_state["ignore_scrape"].update(df_matches["ITEM"].tolist())
                        st.session_state.pop("last_scrape_hash", None)
                        st.session_state.pop("scraped_matches", None)
                        st.rerun()
                st.stop()

        missing_items = jc_df[~jc_df["ITEM_str"].isin(jc_key["ITEM_str"])].copy()
        if not missing_items.empty:
            st.warning(f"⚠️ {len(missing_items)} Items are not in your Database (JCSalesKey).")
            edit_df = pd.DataFrame({"ITEM": missing_items["ITEM_str"], "UPC1": "", "UPC2": "", "DESCRIPTION": missing_items["DESCRIPTION"], "PACK": missing_items["PACK"], "COST": missing_items["COST"]})
            edited_rows = st.data_editor(edit_df, num_rows="dynamic", key="jc_missing_items")
            if st.button("Save New Items to Database", type="primary"):
                to_insert = edited_rows[edited_rows["UPC1"].str.strip() != ""].copy()
                if not to_insert.empty:
                    conn = get_db_connection()
                    to_insert.to_sql("JCSalesKey", conn.engine, if_exists='append', index=False)
                    st.success("Items saved! Re-analyzing invoice...")
                    st.rerun()
                else: st.error("Please enter at least one UPC1 to save.")
            
        mapped_inv = jc_df[jc_df["ITEM_str"].isin(jc_key["ITEM_str"])].merge(jc_key, on="ITEM_str", how="left", suffixes=("", "_db"))
        def resolve_upc(row):
            u1, u2 = _norm_upc_12(row.get("UPC1", "")), _norm_upc_12(row.get("UPC2", ""))
            return u1 if u1 in pb_upcs else (u2 if u2 in pb_upcs else None)
            
        mapped_inv["Resolved_UPC"] = mapped_inv.apply(resolve_upc, axis=1)
        no_match_upcs = mapped_inv[mapped_inv["Resolved_UPC"].isna()].copy()
        
        if not no_match_upcs.empty:
            st.error(f"⚠️ {len(no_match_upcs)} Items were found in the database, but their UPC is 'No Match' in the Pricebook.")
            fix_df = pd.DataFrame({"ITEM": no_match_upcs["ITEM_str"], "Current UPC1": no_match_upcs["UPC1"], "Correct UPC1": "", "DESCRIPTION": no_match_upcs["DESCRIPTION"]})
            fixed_rows = st.data_editor(fix_df, hide_index=True, key="jc_fix_upcs")
            if st.button("Update Database UPCs", type="primary"):
                updates = fixed_rows[fixed_rows["Correct UPC1"].str.strip() != ""]
                if not updates.empty:
                    conn = get_db_connection()
                    with conn.session as session:
                        for _, r in updates.iterrows():
                            session.execute(text('UPDATE "JCSalesKey" SET "UPC1" = :u WHERE "ITEM" = :i'), {"u": str(r["Correct UPC1"]).strip(), "i": str(r["ITEM"]).strip()})
                        session.commit()
                    st.success("Database updated! Re-analyzing invoice...")
                    st.rerun()
                else: st.error("No corrections were entered.")
            
        valid_inv = mapped_inv[mapped_inv["Resolved_UPC"].notna()].copy()
        if valid_inv.empty:
            st.warning("Waiting for missing items to be mapped...")
        else:
            st.success(f"✅ {len(valid_inv)} items successfully mapped to the {PRICEBOOK_TABLE}!")
            final_check = valid_inv.merge(pb_df, left_on="Resolved_UPC", right_on="_norm_upc", how="left")
            final_check["Inv_Unit_Cents"] = (pd.to_numeric(final_check["UNIT"], errors="coerce").fillna(0) * 100).round().astype(int)
            final_check["PB_Unit_Cents"] = (pd.to_numeric(final_check["cost_cents"], errors="coerce").fillna(0) / pd.to_numeric(final_check["cost_qty"], errors="coerce").fillna(1).replace(0, 1)).round().astype(int)
            final_check["Diff"] = final_check["Inv_Unit_Cents"] - final_check["PB_Unit_Cents"]
            changes = final_check[abs(final_check["Diff"]) > 1].copy()
            log_activity(selected_store, vendor, len(jc_df), len(changes))
            
            ready_for_pos, edited_changes = False, None
            if not changes.empty:
                st.error(f"{len(changes)} Unit Cost Changes Detected")
                display_changes = pd.DataFrame({"Item Number": changes["ITEM_str"], "Barcode": changes["Resolved_UPC"], "Item": changes["DESCRIPTION"], "Old Unit Cost": changes["PB_Unit_Cents"] / 100.0, "New Unit Cost": changes["Inv_Unit_Cents"] / 100.0, "Now": pd.to_numeric(changes["cents"], errors="coerce").fillna(0) / 100.0, "New Price": None})
                edited_changes = st.data_editor(display_changes, column_config={"Item Number": st.column_config.TextColumn(disabled=True), "Barcode": st.column_config.TextColumn(disabled=True), "Item": st.column_config.TextColumn(disabled=True), "Old Unit Cost": st.column_config.NumberColumn(format="$%.2f", disabled=True), "New Unit Cost": st.column_config.NumberColumn(format="$%.2f", disabled=True), "Now": st.column_config.NumberColumn("Now ($)", format="$%.2f", disabled=True), "New Price": st.column_config.NumberColumn("New Price ($)", format="$%.2f", min_value=0.0)}, use_container_width=True, hide_index=True)
                if st.button("Confirm Prices & Generate POS", type="primary"):
                    st.session_state["jc_pos_ready"] = True
                    st.session_state["jc_edited_changes"] = edited_changes
                    st.session_state["jc_final_check"] = final_check
                if st.session_state.get("jc_pos_ready"):
                    st.success("Prices confirmed! Ready for download.")
                    ready_for_pos, edited_changes, final_check = True, st.session_state["jc_edited_changes"], st.session_state["jc_final_check"]
            else:
                st.success("All mapped items match Pricebook costs.")
                ready_for_pos = True
                
            if ready_for_pos:
                st.divider()
                st.subheader("POS Update File")
                pos_out = pd.DataFrame()
                pos_out["Upc"] = final_check["Resolved_UPC"].astype(str).apply(lambda u: f'="{str(u).replace("=", "").replace("\"", "").strip()}"')
                pos_out["cost_cents"] = final_check["Inv_Unit_Cents"]
                pos_out["cost_qty"] = 1
                pos_out["addstock"] = 0 
                
                user_prices = dict(zip(edited_changes[edited_changes["New Price"].notna() & (edited_changes["New Price"] > 0)]["Barcode"], edited_changes[edited_changes["New Price"].notna() & (edited_changes["New Price"] > 0)]["New Price"])) if edited_changes is not None and "New Price" in edited_changes.columns else {}
                final_check["User_New_Price"] = final_check["Resolved_UPC"].map(user_prices)

                for col in ["Department", "qty", "cents", "incltaxes", "inclfees", "ebt", "byweight", "Fee Multiplier", "size", "Name"]:
                    if col == "cents":
                        base_cents = pd.to_numeric(final_check["cents"], errors='coerce').fillna(0).astype(int)
                        mask = final_check["User_New_Price"].notna()
                        base_cents[mask] = (final_check.loc[mask, "User_New_Price"] * 100).astype(int)
                        pos_out["cents"] = base_cents
                    elif col in final_check.columns: pos_out[col] = final_check[col]
                    else: pos_out[col] = "" 
                        
                final_pos_out = pos_out[["Upc", "Department", "qty", "cents", "incltaxes", "inclfees", "Name", "size", "ebt", "byweight", "Fee Multiplier", "cost_qty", "cost_cents", "addstock"]].copy()
                num_price_updates = (final_check["User_New_Price"] > 0).sum() if "User_New_Price" in final_check.columns else 0
                st.caption(f"Ready to update costs for {len(final_pos_out)} items and update price for {num_price_updates} items.")
                st.download_button("⬇️ Download POS Update CSV", to_csv_bytes(final_pos_out), f"POS_Update_JCSales_{datetime.today().strftime('%Y-%m-%d')}.csv", "text/csv")

            st.divider()
            with st.expander("View All Invoice Items & Retail Math"):
                review_merged = jc_df.merge(jc_key, on="ITEM_str", how="left", suffixes=("", "_db"))
                pb_now_map = dict(zip(pb_df["_norm_upc"], pd.to_numeric(pb_df["cents"], errors="coerce").fillna(0) / 100.0))
                def get_display_upc_and_now(row):
                    if pd.isna(row.get("UPC1")): return "", None
                    u1, u2 = _norm_upc_12(row.get("UPC1", "")), _norm_upc_12(row.get("UPC2", ""))
                    if u1 and u1 in pb_upcs: return u1, pb_now_map.get(u1, None)
                    if u2 and u2 in pb_upcs: return u2, pb_now_map.get(u2, None)
                    return "No Match", None
                upc_now = review_merged.apply(get_display_upc_and_now, axis=1, result_type="expand")
                st.dataframe(pd.DataFrame({"Item Number": review_merged["ITEM_str"], "Upc": upc_now[0], "Description": review_merged["DESCRIPTION"], "Unit": pd.to_numeric(review_merged["UNIT"], errors="coerce"), "Now": upc_now[1], "Retail": pd.to_numeric(review_merged["UNIT"], errors="coerce") * 2}), column_config={"Unit": st.column_config.NumberColumn("Unit ($)", format="$%.2f"), "Now": st.column_config.NumberColumn("Now ($)", format="$%.2f"), "Retail": st.column_config.NumberColumn("Retail ($)", format="$%.2f")}, use_container_width=True, hide_index=True)

# --- SG / NV / Breakthru ---
elif vendor in ["Southern Glazer's", "Nevada Beverage", "Breakthru"]:
    st.info(f"Using **BeerandLiquorKey** Map + **{PRICEBOOK_TABLE}**")
    if st.session_state.get("current_sg_vendor") != vendor:
        st.session_state["analyze_sg"] = False
        st.session_state["current_sg_vendor"] = vendor
        if "sg_pos_ready" in st.session_state: del st.session_state["sg_pos_ready"]
        
    inv_files = st.file_uploader(f"Upload {vendor} Invoice(s)", accept_multiple_files=True)
    if not inv_files: st.session_state["analyze_sg"] = False
    if st.button("Analyze Invoice"):
        st.session_state["analyze_sg"] = True
        if "sg_pos_ready" in st.session_state: del st.session_state["sg_pos_ready"]
        
    if st.session_state.get("analyze_sg", False) and inv_files:
        map_df = load_vendor_map(VENDOR_MAP_TABLE)
        pb_df = load_pricebook(PRICEBOOK_TABLE)
        if map_df.empty: 
            st.error("Vendor Map is empty. Go to Admin.")
            st.stop()
        
        rows = []
        for f in inv_files:
            f.seek(0)
            if vendor == "Southern Glazer's": rows.append(SouthernGlazersParser().parse(f))
            elif vendor == "Nevada Beverage": rows.append(NevadaBeverageParser().parse(f))
            elif vendor == "Breakthru": rows.append(BreakthruParser().parse(f))
        
        if not rows: st.stop()
        inv_df = pd.concat(rows, ignore_index=True)
        if "Item Number" not in inv_df.columns: inv_df["Item Number"] = ""
        
        map_df["_map_key"] = map_df["Invoice UPC"].astype(str).apply(_norm_upc_12)
        inv_df["_key_item"] = inv_df["Item Number"].astype(str).apply(_norm_upc_12)
        inv_df["_key_upc"] = inv_df["UPC"].astype(str).apply(_norm_upc_12)
        
        merged_item = inv_df.merge(map_df, left_on="_key_item", right_on="_map_key", how="left", suffixes=("", "_map"))
        mask_matched = merged_item["Full Barcode"].notna()
        unmatched_df = inv_df[~inv_df.index.isin(merged_item[mask_matched].index)].copy()
        
        if not unmatched_df.empty:
            merged_upc = unmatched_df.merge(map_df, left_on="_key_upc", right_on="_map_key", how="left", suffixes=("", "_map"))
            mapped = pd.concat([merged_item[mask_matched], merged_upc], ignore_index=True)
        else: mapped = merged_item

        missing = mapped[mapped["Full Barcode"].isna()].copy()
        valid = mapped[mapped["Full Barcode"].notna()].copy()
        
        st.markdown(f"### 📊 Status Report\n* **Items Found on Invoice:** {len(inv_df)}\n* **Successfully Mapped:** {len(valid)}\n* **Missing from Map:** {len(missing)}")
        st.subheader("Invoice Items Found")
        st.dataframe(inv_df, use_container_width=True)
        
        if not missing.empty:
            st.warning(f"⚠️ {len(missing)} items are not in your Database Map.")
            missing["_display_id"] = missing["Item Number"]
            missing.loc[missing["_display_id"] == "", "_display_id"] = missing["UPC"]
            
            edit_df = pd.DataFrame({"Full Barcode": "", "Invoice UPC": missing["_display_id"], "0": "", "Name": missing["Item Name"], "Size": "", "PACK": 1, "Company": "Southern" if vendor == "Southern Glazer's" else "Nevada" if vendor == "Nevada Beverage" else vendor, "type": ""})
            edited_rows = st.data_editor(edit_df, num_rows="dynamic", key="editor_missing", column_config={"type": st.column_config.SelectboxColumn("Type", options=["Beer", "Liquor", ""])})
            
            if st.button("Save New Items to Map"):
                to_insert = edited_rows[edited_rows["Full Barcode"].astype(str).str.len() > 3].copy()
                if not to_insert.empty:
                    conn = get_db_connection()
                    to_insert["Invoice UPC"] = to_insert["Invoice UPC"].astype(str)
                    to_insert["Full Barcode"] = to_insert["Full Barcode"].astype(str)
                    to_insert.to_sql(VENDOR_MAP_TABLE, conn.engine, if_exists='append', index=False)
                    st.success("Items successfully mapped! Re-analyzing invoice...")
                    time.sleep(1)
                    st.rerun() 
                else: st.error("No valid Barcodes were entered.")

        if not valid.empty:
            valid["_sys_upc_norm"] = valid["Full Barcode"].astype(str).apply(_norm_upc_12)
            final_check = valid.merge(pb_df, left_on="_sys_upc_norm", right_on="_norm_upc", how="left")
            final_check["Inv_Cost_Cents"] = (pd.to_numeric(final_check["Cost"], errors='coerce') * 100).fillna(0).astype(int)
            final_check["PB_Cost_Cents"] = final_check["cost_cents"].fillna(0).astype(int)
            final_check["Diff"] = final_check["Inv_Cost_Cents"] - final_check["PB_Cost_Cents"]
            
            changes = final_check[abs(final_check["Diff"]) > 1].copy()
            log_activity(selected_store, vendor, len(inv_df), len(changes))
            
            ready_for_pos, edited_changes = False, None
            if not changes.empty:
                st.error(f"{len(changes)} Cost Changes Detected")
                display_changes = pd.DataFrame({"Barcode": changes["Full Barcode"], "Item": changes["Name_y"] if "Name_y" in changes.columns else (changes["Name_x"] if "Name_x" in changes.columns else changes["Name"]), "Old Cost": changes["PB_Cost_Cents"] / 100.0, "New Cost": changes["Inv_Cost_Cents"] / 100.0, "New Price": None})
                edited_changes = st.data_editor(display_changes, column_config={"Barcode": st.column_config.TextColumn(disabled=True), "Item": st.column_config.TextColumn(disabled=True), "Old Cost": st.column_config.NumberColumn(format="$%.2f", disabled=True), "New Cost": st.column_config.NumberColumn(format="$%.2f", disabled=True), "New Price": st.column_config.NumberColumn("New Price ($)", format="$%.2f", min_value=0.0)}, use_container_width=True, hide_index=True)
                if st.button("Confirm Prices & Generate POS", type="primary"):
                    st.session_state["sg_pos_ready"] = True
                    st.session_state["sg_edited_changes"] = edited_changes
                    st.session_state["sg_final_check"] = final_check
                if st.session_state.get("sg_pos_ready"):
                    st.success("Prices confirmed! Ready for download.")
                    ready_for_pos, edited_changes, final_check = True, st.session_state["sg_edited_changes"], st.session_state["sg_final_check"]
            else:
                st.success("All mapped items match Pricebook costs.")
                ready_for_pos = True

            if ready_for_pos:
                st.divider()
                st.subheader("POS Update File")
                pos_out = pd.DataFrame()
                pos_out["Upc"] = final_check["Full Barcode"].astype(str).apply(lambda u: f'="{str(u).replace("=", "").replace("\"", "").strip()}"')
                pos_out["cost_cents"] = final_check["Inv_Cost_Cents"]
                pos_out["cost_qty"] = pd.to_numeric(final_check["PACK"], errors='coerce').fillna(1).astype(int)
                
                qty_col = "Cases" if "Cases" in final_check.columns else "Qty"
                total_actual_cases = 0
                if qty_col in final_check.columns:
                    cases = pd.to_numeric(final_check[qty_col], errors='coerce').fillna(0)
                    pos_out["addstock"] = (cases * pos_out["cost_qty"]).astype(int)
                    total_actual_cases = int(cases.sum())
                else: pos_out["addstock"] = 0

                pos_out["Name"] = final_check["Name_y"] if "Name_y" in final_check.columns else (final_check["Name_x"] if "Name_x" in final_check.columns else (final_check["Name"] if "Name" in final_check.columns else ""))
                
                user_prices = dict(zip(edited_changes[edited_changes["New Price"].notna() & (edited_changes["New Price"] > 0)]["Barcode"], edited_changes[edited_changes["New Price"].notna() & (edited_changes["New Price"] > 0)]["New Price"])) if edited_changes is not None and "New Price" in edited_changes.columns else {}
                final_check["User_New_Price"] = final_check["Full Barcode"].map(user_prices)

                for col in ["Department", "qty", "cents", "incltaxes", "inclfees", "ebt", "byweight", "Fee Multiplier"]:
                    if col == "cents":
                        base_cents = pd.to_numeric(final_check["cents"], errors='coerce').fillna(0).astype(int)
                        mask = final_check["User_New_Price"].notna()
                        base_cents[mask] = (final_check.loc[mask, "User_New_Price"] * 100).astype(int)
                        pos_out["cents"] = base_cents
                    elif col in final_check.columns: pos_out[col] = final_check[col]
                    else: pos_out[col] = "" 

                pos_out["size"] = final_check["size"] if "size" in final_check.columns else (final_check["Size"] if "Size" in final_check.columns else "")
                final_pos_out = pos_out[["Upc", "Department", "qty", "cents", "incltaxes", "inclfees", "Name", "size", "ebt", "byweight", "Fee Multiplier", "cost_qty", "cost_cents", "addstock"]].copy()
                num_price_updates = (final_check["User_New_Price"] > 0).sum() if "User_New_Price" in final_check.columns else 0
                st.caption(f"Ready to update stock for {len(final_pos_out)} items and update price for {num_price_updates} items (Total Cases: {total_actual_cases})")
                st.download_button("⬇️ Download POS Update CSV", to_csv_bytes(final_pos_out), f"POS_Update_{vendor}_{datetime.today().strftime('%Y-%m-%d')}.csv", "text/csv")

# --- COSTCO ---
elif vendor == "Costco":
    st.header("Costco Processor")
    st.markdown("**Note:** Upload your Costco Master List manually.")
    
    costco_master = st.file_uploader("Upload Costco Master List (XLSX)", type=["xlsx"], key="costco_master")
    costco_text = st.text_area("Paste Costco Receipt Text", height=200, key="costco_text")

    if st.button("Process Costco Receipt"):
        if not costco_master or not costco_text: st.error("Please provide both Master file and Receipt text.")
        else:
            try:
                parsed_df = CostcoParser().parse(costco_text)
                if parsed_df.empty: st.error("No items found in receipt.")
                else:
                    master_df = pd.read_excel(costco_master, dtype=str)
                    m_item_num = next((c for c in ["Item Number", "Item #"] if c in master_df.columns), "Item Number")
                    m_cost = next((c for c in ["Cost"] if c in master_df.columns), "Cost")
                    
                    master_df["_item_str"] = master_df[m_item_num].astype(str).str.strip()
                    item_cost_map = dict(zip(master_df["_item_str"], pd.to_numeric(master_df[m_cost], errors="coerce").fillna(0.0)))
                    
                    parsed_df["Item Number"] = parsed_df["Item Number"].astype(str).str.strip()
                    results = []
                    for _, row in parsed_df.iterrows():
                        item = row["Item Number"]
                        price = float(row["Receipt Price"])
                        known_cost = item_cost_map.get(item, 0.0)
                        qty = 1
                        if known_cost > 0:
                            ratio = price / known_cost
                            if abs(ratio - round(ratio)) < 0.05: qty = max(1, int(round(ratio)))
                        results.append({"Item Number": item, "Description": row["Item Name"], "Receipt Price": price, "Calc Qty": qty, "Unit Cost": price / qty})
                    
                    res_df = pd.DataFrame(results)
                    st.success(f"Processed {len(res_df)} items.")
                    st.dataframe(res_df)
                    st.download_button("⬇️ Download Costco Report", to_xlsx_bytes({"Costco": res_df}), "Costco_Report.xlsx")
            except Exception as e:
                st.error(f"Error processing master/receipt: {e}")
