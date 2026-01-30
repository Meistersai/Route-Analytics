import streamlit as st
import pandas as pd
import requests
import polyline
import textwrap
import io
import time
import gc 
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
import os

# --- 1. CONFIGURATION & INITIALIZATION ---
st.set_page_config(page_title="Route Analytics Pro", layout="wide")

# Custom CSS for Professional Light Mode Look
st.markdown("""
<style>
    /* Global Background - Clean Light Gray */
    .stApp { 
        background-color: #f8fafc; 
        color: #1e293b; 
    }
    
    /* Premium White Card with Soft Shadow */
    .react-card {
        background: #ffffff;
        border: 1px solid #e2e8f0;
        border-radius: 1rem;
        padding: 1.5rem;
        color: #1e293b;
        margin-bottom: 2rem;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
    }
    
    /* Vibrant Gradients for Metrics */
    .text-grad-sky { 
        background: linear-gradient(to right, #2563eb, #3b82f6); 
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
        font-size: 2.5rem; font-weight: 800; line-height: 1; 
    }
    .text-grad-orange { 
        background: linear-gradient(to right, #ea580c, #f59e0b); 
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
        font-size: 2.5rem; font-weight: 800; line-height: 1; 
    }
    
    /* Breakdown Boxes for Light Mode */
    .breakdown-box { 
        background: #f1f5f9; 
        border-radius: 0.5rem; 
        padding: 0.75rem; 
        border: 1px solid #e2e8f0; 
        color: #475569;
        font-weight: 600;
    }
    
    /* Timeline Container */
    .route-container { 
        background-color: #ffffff; 
        padding: 1.25rem; 
        border-radius: 1rem; 
        color: #1e293b; 
        border: 1px solid #e2e8f0;
    }
    
    .leg-card { 
        display: flex; 
        justify-content: space-between; 
        align-items: center; 
        padding: 1rem; 
        border-radius: 0.75rem; 
        border: 1px solid #e2e8f0; 
        margin-bottom: 8px; 
        background: white; 
    }
    
    /* Mode Indicators */
    .leg-land { border-left: 5px solid #10b981; }
    .leg-sea { border-left: 5px solid #3b82f6; }
    
    /* Form Inputs Overrides */
    div[data-baseweb="input"] { background-color: white !important; }
    .stRadio div[role="radiogroup"] { gap: 20px; }
</style>
""", unsafe_allow_html=True)

if 'journey_data' not in st.session_state:
    st.session_state.journey_data = None

# --- 2. LOGIC ENGINES (Unchanged for reliability) ---
def clean_location(raw):
    geolocator = Nominatim(user_agent="route_pro_light_v10")
    corrections = {"UK": "United Kingdom", "USA": "United States", "UAE": "United Arab Emirates", "PH": "Philippines"}
    search_query = str(raw)
    for abbr, full in corrections.items():
        if search_query.endswith(abbr) or f" {abbr}" in search_query:
            search_query = search_query.replace(abbr, full)
    try:
        time.sleep(1.2)
        loc = geolocator.geocode(search_query, addressdetails=True, timeout=10)
        if loc:
            d = loc.raw['address']
            clean = f"{d.get('city') or d.get('town') or d.get('suburb') or ''}, {d.get('country') or ''}".strip(", ")
            return loc.latitude, loc.longitude, clean or search_query
    except: pass
    return None, None, None

@st.cache_data
def load_hubs():
    p, a = pd.DataFrame(), pd.DataFrame()
    try:
        p_air = 'AirportLists.csv' if os.path.exists('AirportLists.csv') else 'PortDistanceApp/AirportLists.csv'
        p_sea = 'SeaportList.csv' if os.path.exists('SeaportList.csv') else 'PortDistanceApp/SeaportList.csv'
        a = pd.read_csv(p_air, header=None, encoding='latin1').rename(columns={1:'name', 6:'lat', 7:'lon'})
        p = pd.read_csv(p_sea, encoding='latin1')
        p.rename(columns={'port_name':'name','latitude':'lat','longitude':'lon'}, inplace=True, errors='ignore')
    except: pass
    return p, a

def calculate(o, d, m):
    db_p, db_a = load_hubs()
    l_o, n_o, c_o = clean_location(o)
    l_d, n_d, c_d = clean_location(d)
    if l_o is None or l_d is None: return None

    legs, bk = [], {"land": 0, "air": 0, "sea": 0}
    if m.lower() == 'land':
        dist = geodesic((l_o, n_o), (l_d, n_d)).kilometers * 1.3
        legs.append({"from": c_o, "to": c_d, "dist": dist, "icon": "🚗", "type": "land", "desc": "Road Route", "coords": [(l_o, n_o), (l_d, n_d)]})
        bk['land'] = dist
    else:
        hubs = db_p if m.lower() == 'sea' else db_a
        hubs['t1'] = (hubs['lat'] - l_o)**2 + (hubs['lon'] - n_o)**2
        h1 = hubs.loc[hubs['t1'].idxmin()]
        hubs['t2'] = (hubs['lat'] - l_d)**2 + (hubs['lon'] - n_d)**2
        h2 = hubs.loc[hubs['t2'].idxmin()]
        d1, d2, d3 = geodesic((l_o, n_o), (h1['lat'], h1['lon'])).kilometers * 1.2, geodesic((h1['lat'], h1['lon']), (h2['lat'], h2['lon'])).kilometers, geodesic((h2['lat'], h2['lon']), (l_d, n_d)).kilometers * 1.2
        legs = [
            {"from": c_o, "to": h1['name'], "dist": d1, "icon": "🚗", "type": "land", "desc": "To Hub", "coords": [(l_o, n_o), (h1['lat'], h1['lon'])]},
            {"from": h1['name'], "to": h2['name'], "dist": d2, "icon": "🚢" if m.lower()=='sea' else "✈️", "type": "sea", "desc": "Main Transit", "coords": [(h1['lat'], h1['lon']), (h2['lat'], h2['lon'])]},
            {"from": h2['name'], "to": c_d, "dist": d3, "icon": "🚗", "type": "land", "desc": "To Final", "coords": [(h2['lat'], h2['lon']), (l_d, n_d)]}
        ]
        bk['land'], bk[m.lower()] = (d1+d3), d2
    
    total = sum(leg['dist'] for leg in legs)
    hours = total / (65 if m=='land' else (35 if m=='sea' else 800))
    return {"total_km": total, "total_mi": total*0.62, "time": f"{int(hours)}h", "legs": legs, "clean_o": c_o, "clean_d": c_d, "start": (l_o, n_o), "breakdown": bk}

# --- 3. UI TABS ---
t1, t2 = st.tabs(["📍 Single Journey", "📂 Bulk Processing"])

with t1:
    cola, colb = st.columns([1, 1.5])
    with cola:
        st.subheader("Route Configuration")
        with st.form("single_form"):
            o_in = st.text_input("Origin Address", "Beverley, UK")
            d_in = st.text_input("Destination Address", "Sweden")
            m_in = st.radio("Transport Mode", ["Air", "Sea", "Land"], horizontal=True)
            if st.form_submit_button("Calculate Distance"):
                with st.spinner("Analyzing geodata..."):
                    st.session_state.journey_data = calculate(o_in, d_in, m_in)

    with colb:
        if st.session_state.journey_data:
            data = st.session_state.journey_data
            bk = data['breakdown']
            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="color: #64748b; font-size: 0.85rem; font-weight: 600; margin-bottom: 10px;">TOTAL DISTANCE</div>
                    <div style="display:flex; gap:40px; margin-bottom:15px">
                        <div><div class="text-grad-sky">{int(data['total_km']):,}</div><div style="color:#64748b; font-size:12px; font-weight:500">KILOMETERS</div></div>
                        <div><div class="text-grad-orange">{int(data['total_mi']):,}</div><div style="color:#64748b; font-size:12px; font-weight:500">MILES</div></div>
                    </div>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; border-top:1px solid #e2e8f0; padding-top:15px">
                        <div class="breakdown-box">🚗 {int(bk['land']):,} km</div>
                        <div class="breakdown-box">✈️ {int(bk['air']):,} km</div>
                        <div class="breakdown-box">🚢 {int(bk['sea']):,} km</div>
                    </div>
                </div>
            """), unsafe_allow_html=True)
            m = folium.Map(location=data['start'], zoom_start=4)
            for leg in data['legs']: folium.PolyLine(leg['coords'], color="#2563eb", weight=4).add_to(m)
            st_folium(m, height=350, use_container_width=True)
        else:
            st.markdown("<div style='text-align:center; padding:50px; border:2px dashed #cbd5e1; border-radius:1rem; background:white;'><h3>🌍 Supply Chain Intelligence</h3><p>Enter an origin and destination to begin analysis.</p></div>", unsafe_allow_html=True)

with t2:
    st.markdown("### Bulk Operations")
    up = st.file_uploader("Upload Logistics CSV", type="csv")
    if up:
        try: df = pd.read_csv(up)
        except: 
            up.seek(0)
            df = pd.read_csv(up, encoding='latin1')
        
        st.write(f"📁 Records detected: {len(df)}")
        if st.button("🚀 Execute Batch Analysis"):
            results, prog, chunk_size = [], st.progress(0), 50
            for start in range(0, len(df), chunk_size):
                end = min(start + chunk_size, len(df))
                chunk = df.iloc[start:end]
                for i, row in chunk.iterrows():
                    j = calculate(str(row[0]), str(row[1]), str(row[2]))
                    results.append({"Total_KM": round(j['total_km'],1) if j else "Err", "Time": j['time'] if j else "-"})
                    prog.progress((len(results))/len(df))
                gc.collect() 
            
            final_df = pd.concat([df, pd.DataFrame(results)], axis=1)
            st.dataframe(final_df, use_container_width=True)
            st.download_button("📥 Export Results to CSV", final_df.to_csv(index=False), "logistics_analysis.csv")
