import streamlit as st
import pandas as pd
import ezdxf
import tempfile
import os
from pyproj import Transformer

transformer = Transformer.from_crs("EPSG:4326", "EPSG:2248", always_xy=True)

def process_multiple_csvs(uploaded_files):
    dfs = []
    base_cols = None

    for idx, uploaded_file in enumerate(uploaded_files):
        df = pd.read_csv(uploaded_file, dtype=str, keep_default_na=False, na_filter=False)
        if idx == 0:
            base_cols = df.columns.tolist()
        else:
            df = df.reindex(columns=base_cols, fill_value='')
        df["Layer"] = os.path.splitext(uploaded_file.name)[0]
        dfs.append(df)

    all_pts = pd.concat(dfs, ignore_index=True)

    for col in ['Latitude', 'Longitude', 'Elevation', 'Instrument Ht', 'Ortho Height']:
        if col in all_pts.columns:
            all_pts[col] = pd.to_numeric(all_pts[col], errors='coerce')

    all_pts['Instrument Ht'] = all_pts.get('Instrument Ht', pd.Series(0, dtype=float))
    all_pts = all_pts.dropna(subset=['Latitude', 'Longitude', 'Elevation'])

    out = []
    for _, r in all_pts.iterrows():
        lat, lon = float(r['Latitude']), float(r['Longitude'])
        ell_h = float(r['Elevation'])
        inst_h = float(r['Instrument Ht'])
        ortho_h = float(r.get('Ortho Height', ell_h))
        h_corr = ell_h - inst_h
        ortho_corr = ortho_h - inst_h
        x, y = transformer.transform(lon, lat)
        out.append({
            **r,
            'Ortho_ft': ortho_corr * 3.280833333,
            'X_ft': x,
            'Y_ft': y,
        })

    df_out = pd.DataFrame(out)

    # Sort by integer ID if it exists
    if 'ID' in df_out.columns:
        df_out['ID_int'] = pd.to_numeric(df_out['ID'], errors='coerce').fillna(0).astype(int)
        df_out = df_out.sort_values('ID_int').drop(columns=['ID_int'])
    else:
        df_out = df_out.reset_index(drop=True)

    # Save processed CSV to a temporary file
    temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8")
    df_out.to_csv(temp_csv.name, index=False)

    # Generate DXF
    doc = ezdxf.new()
    msp = doc.modelspace()
    size = 0.05
    txt_size = 0.3
    for _, row in df_out.iterrows():
        x, y, z = row['X_ft'], row['Y_ft'], row['Ortho_ft']
        layer = 'v-' + row.get('Layer', 'default')
        fix = float(row.get('Fix ID', 0))
        remarks = row.get('Remarks', '')
        color = ezdxf.colors.RED if fix == 4 else ezdxf.colors.YELLOW

        for lname in [layer, f"{layer}-X", f"{layer}-ORTHO", f"{layer}-ANNO"]:
            if lname not in doc.layers:
                doc.layers.new(name=lname)

        msp.add_line((x - size, y - size, z), (x + size, y + size, z), dxfattribs={'layer': f"{layer}-X", 'color': color})
        msp.add_line((x - size, y + size, z), (x + size, y - size, z), dxfattribs={'layer': f"{layer}-X", 'color': color})
        if fix == 5:
            msp.add_line((x - size, y, z), (x + size, y, z), dxfattribs={'layer': f"{layer}-X", 'color': color})
        msp.add_text(f"{z:.2f}", dxfattribs={'layer': f"{layer}-ORTHO", 'height': txt_size, 'insert': (x + size, y + size, z), 'color': color})
        if not pd.isna(remarks):
            msp.add_text(remarks, dxfattribs={'layer': f"{layer}-ANNO", 'height': txt_size, 'insert': (x + size, y - size - txt_size, z), 'color': color})

    temp_dxf = tempfile.NamedTemporaryFile(delete=False, suffix=".dxf")
    doc.saveas(temp_dxf.name)

    return temp_dxf.name, temp_csv.name  # Return both DXF and CSV paths


# Streamlit UI
st.set_page_config(page_title="CSV to DXF Converter", layout="centered")
st.title("📐 CSV to DXF Converter")

uploaded_files = st.file_uploader("Upload multiple CSV files", type="csv", accept_multiple_files=True)

if uploaded_files:
    st.success(f"{len(uploaded_files)} file(s) uploaded successfully.")
    if st.button("Generate Files"):
        with st.spinner("Processing and generating files..."):
            dxf_file, csv_file = process_multiple_csvs(uploaded_files)

            # Download DXF
            with open(dxf_file, "rb") as f:
                st.download_button("📥 Download DXF", f, file_name="combined_output.dxf", mime="application/dxf")

            # Download CSV
            with open(csv_file, "rb") as f:
                st.download_button("📥 Download Combined CSV", f, file_name="processed_points.csv", mime="text/csv")
