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
