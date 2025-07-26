import streamlit as st
import pandas as pd
import ezdxf
import tempfile
import os
from pyproj import Transformer
import numpy as np

transformer = Transformer.from_crs("EPSG:4326", "EPSG:2248", always_xy=True)

def parse_geometry(geometry_str):
    if geometry_str.startswith("POINTZ"):
        coords = geometry_str.strip("POINTZ() ").split()
        return [(float(coords[0]), float(coords[1]), float(coords[2]))]
    elif geometry_str.startswith("LINESTRINGZ"):
        coords = geometry_str.strip("LINESTRINGZ() ").split(",")
        return [tuple(map(float, c.strip().split())) for c in coords]
    elif geometry_str.startswith("POLYGONZ"):
        coords = geometry_str.strip("POLYGONZ() ").strip("(").strip(")").split(",")
        return [tuple(map(float, c.strip().split())) for c in coords]
    else:
        return []

def transform_point(lon, lat, elev, inst_ht):
    x, y = transformer.transform(lon, lat)
    z = (elev + 34.67 - inst_ht) * 3.28084
    return x, y, z

def add_point_marker(msp, x, y, z, size, layer, color):
    msp.add_line((x - size, y - size, z), (x + size, y + size, z), dxfattribs={'layer': layer, 'color': color})
    msp.add_line((x - size, y + size, z), (x + size, y - size, z), dxfattribs={'layer': layer, 'color': color})

def add_text(msp, text, x, y, z, txt_size, layer, color):
    msp.add_text(text, dxfattribs={'layer': layer, 'height': txt_size, 'insert': (x, y, z), 'color': color})

def process_csvs(uploaded_files, marker_size, txt_size):
    doc = ezdxf.new()
    msp = doc.modelspace()
    all_records = []

    for uploaded_file in uploaded_files:
        df = pd.read_csv(uploaded_file, keep_default_na=False)
        if 'Geometry' not in df.columns:
            continue
        for _, row in df.iterrows():
            name = row.get('Name', row.get('ID', ''))
            remarks = row.get('Remarks', '')
            inst_ht = float(row.get('Instrument Ht', 1.6))
            geometry = row['Geometry']
            coords = parse_geometry(geometry)
            if geometry.startswith("POINTZ"):
                lon, lat, elev = coords[0]
                x, y, z = transform_point(lon, lat, elev, inst_ht)
                fix = float(row.get('Fix ID', 0))
                color = ezdxf.colors.RED if fix == 4 else ezdxf.colors.YELLOW
                layer = 'v-points'
                if layer not in doc.layers:
                    doc.layers.new(name=layer, dxfattribs={'color': ezdxf.colors.YELLOW})
                add_point_marker(msp, x, y, z, marker_size, layer, color)
                add_text(msp, f"{z:.2f}", x + marker_size, y + marker_size, z, txt_size, layer, color)
                if remarks:
                    add_text(msp, remarks, x + marker_size, y - marker_size - txt_size, z, txt_size, layer, color)
                all_records.append({'Type': 'Point', 'Name': name, 'Remarks': remarks, 'X_ft': x, 'Y_ft': y, 'Z_ft': z})
            elif geometry.startswith("LINESTRINGZ"):
                # For lines, third value is actually elevation, not width. Width fixed to 0.
                vertices = [transform_point(lon, lat, elev, inst_ht) for lon, lat, elev in coords]
                layer = f"v-lines-{name}"
                if layer not in doc.layers:
                    doc.layers.new(name=layer, dxfattribs={'color': ezdxf.colors.BLUE})
                # Create polyline with width 0 and actual Z assigned from the elevation
                lwpoly = msp.add_lwpolyline([(vx, vy) for vx, vy, vz in vertices], dxfattribs={'layer': layer, 'color': 256})
                lwpoly.dxf.elevation = 0  # 2D polyline elevation baseline
                for vx, vy, vz in vertices:
                    msp.add_point((vx, vy, vz), dxfattribs={'layer': layer, 'color': 256})
                    add_point_marker(msp, vx, vy, vz, marker_size, layer, ezdxf.colors.BLUE)
                mid = vertices[len(vertices)//2]
                add_text(msp, name, mid[0], mid[1], mid[2], txt_size, layer, ezdxf.colors.BLUE)
                all_records.append({'Type': 'Line', 'Name': name, 'Remarks': remarks, 'Vertices': vertices})
            elif geometry.startswith("POLYGONZ"):
                vertices = [transform_point(lon, lat, elev, inst_ht) for lon, lat, elev in coords]
                layer = f"v-polygons-{name}"
                if layer not in doc.layers:
                    doc.layers.new(name=layer, dxfattribs={'color': ezdxf.colors.GREEN})
                msp.add_lwpolyline([(vx, vy) for vx, vy, vz in vertices], close=True, dxfattribs={'layer': layer, 'color': 256})
                for vx, vy, vz in vertices:
                    add_point_marker(msp, vx, vy, vz, marker_size, layer, ezdxf.colors.GREEN)
                centroid_x = np.mean([vx for vx, vy, vz in vertices])
                centroid_y = np.mean([vy for vx, vy, vz in vertices])
                centroid_z = np.mean([vz for vx, vy, vz in vertices])
                add_text(msp, f"{name}\n{remarks}", centroid_x, centroid_y, centroid_z, txt_size, layer, ezdxf.colors.GREEN)
                all_records.append({'Type': 'Polygon', 'Name': name, 'Remarks': remarks, 'Vertices': vertices})

    temp_dxf = tempfile.NamedTemporaryFile(delete=False, suffix=".dxf")
    doc.saveas(temp_dxf.name)
    df_out = pd.DataFrame(all_records)
    temp_csv = tempfile.NamedTemporaryFile(delete=False, suffix=".csv", mode="w", newline="", encoding="utf-8")
    df_out.to_csv(temp_csv.name, index=False)
    return temp_dxf.name, temp_csv.name

# --- Streamlit App ---
st.set_page_config(page_title="CSV to DXF Converter (Unified)", layout="centered")
st.title("📐 CSV to DXF Converter (Unified)")

if "dxf_path" not in st.session_state:
    st.session_state.dxf_path = None
    st.session_state.csv_path = None

marker_size = st.slider("Marker Size", 0.01, 1.0, 0.05)
txt_size = st.slider("Text Size", 0.1, 2.0, 0.3)
output_dxf_name = st.text_input("Output DXF filename", "combined_output.dxf")
output_csv_name = st.text_input("Output CSV filename", "combined_summary.csv")

uploaded_files = st.file_uploader("Upload CSV files (points, lines, polygons)", type="csv", accept_multiple_files=True)

if st.button("Generate DXF") and uploaded_files:
    with st.spinner("Processing and generating DXF..."):
        dxf_file, csv_file = process_csvs(uploaded_files, marker_size, txt_size)
        st.session_state.dxf_path = dxf_file
        st.session_state.csv_path = csv_file
        st.success("DXF and CSV generated successfully. Scroll down to download.")

if st.session_state.dxf_path and st.session_state.csv_path:
    with open(st.session_state.dxf_path, "rb") as f:
        st.download_button("📥 Download DXF", f, file_name=output_dxf_name, mime="application/dxf")
    with open(st.session_state.csv_path, "rb") as f:
        st.download_button("📥 Download CSV Summary", f, file_name=output_csv_name, mime="text/csv")
