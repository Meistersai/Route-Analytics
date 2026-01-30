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

# Custom CSS
st.markdown("""
<style>
    /* --- HIDE STREAMLIT BRANDING & HEADER --- */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stHeader"] {display: none;}
    [data-testid="stToolbar"] {visibility: hidden;}
    
    /* Global Background - Clean Light Gray */
    .stApp { 
        background-color: #f8fafc; 
        color: #1e293b; 
        margin-top: -50px; /* Pull content up since header is gone */
    }
    
    /* RESULT CARD: Original Dark Gradient Background */
    .react-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border-radius: 1rem;
        padding: 1.5rem;
        color: white; /* Text must be white on dark bg */
        margin-bottom: 2rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
        border: 1px solid rgba(255, 255, 255, 0.05);
    }
    
    /* Gradient Text for Metrics (Sky & Orange) */
    .text-grad-sky { 
        background: linear-gradient(to right, #38bdf8, #67e8f9); 
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
        font-size: 2.5rem; font-weight: 800; line-height: 1; 
    }
    .text-grad-orange { 
        background: linear-gradient(to right, #fb923c, #fcd34d); 
        -webkit-background-clip: text; -webkit-text-fill-color: transparent; 
        font-size: 2.5rem; font-weight: 800; line-height: 1; 
    }
    
    /* Breakdown Boxes (Dark Semi-Transparent) */
    .breakdown-box { 
        background: rgba(30, 41, 59, 0.5); 
        border-radius: 0.5rem; 
        padding: 0.75rem; 
        border: 1px solid rgba(255,255,255,0.1); 
        color: #cbd5e1;
        font-weight: 600;
    }
    
    /* Timeline Container & Cards (Light Mode Style) */
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
        position: relative;
        z-index: 2;
    }
    
    /* Mode Indicators */
    .leg-land { border-left: 5px solid #10b981; }
    .leg-sea { border-left: 5px solid #3b82f6; }
    
    /* Icons */
    .icon-box { 
        width: 40px; height: 40px; border-radius: 50%; 
        display: flex; align-items: center; justify-content: center; 
        font-size: 1.2rem; margin-right: 12px; 
    }
    .icon-land { background: #ecfdf5; color: #10b981; }
    .icon-sea { background: #eff6ff; color: #3b82f6; }

    /* Connector Line */
    .connector { display: flex; justify-content: center; align-items: center; height: 24px; position: relative; margin: -2px 0; }
    .conn-line { position: absolute; width: 2px; height: 100%; background: #e2e8f0; left: calc(50% - 1px); z-index: 0; }
    .conn-arrow { z-index: 1; background: #ffffff; color: #94a3b8; padding: 0 4px; font-size: 0.8rem; }
    
    /* Form Inputs Overrides */
    div[data-baseweb="input"] { background-color: white !important; }
    .stRadio div[role="radiogroup"] { gap: 20px; }
</style>
""", unsafe_allow_html=True)

if 'journey_data' not in st.session_state:
    st.session_state.journey_data = None

# --- 2. LOGIC ENGINES ---
def clean_location(raw):
    geolocator = Nominatim(user_agent="route_pro_final_v12")
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
            
            # 1. DARK RESULT CARD
            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="color: #cbd5e1; font-size: 0.85rem; font-weight: 600; margin-bottom: 10px;">TOTAL DISTANCE</div>
                    <div style="display:flex; gap:40px; margin-bottom:15px">
                        <div><div class="text-grad-sky">{int(data['total_km']):,}</div><div style="color:#94a3b8; font-size:12px; font-weight:500">KILOMETERS</div></div>
                        <div><div class="text-grad-orange">{int(data['total_mi']):,}</div><div style="color:#94a3b8; font-size:12px; font-weight:500">MILES</div></div>
                    </div>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:15px">
                        <div class="breakdown-box">🚗 {int(bk['land']):,} km</div>
                        <div class="breakdown-box">✈️ {int(bk['air']):,} km</div>
                        <div class="breakdown-box">🚢 {int(bk['sea']):,} km</div>
                    </div>
                </div>
            """), unsafe_allow_html=True)
            
            # 2. MAP
            m = folium.Map(location=data['start'], zoom_start=4)
            for leg in data['legs']: folium.PolyLine(leg['coords'], color="#2563eb", weight=4).add_to(m)
            st_folium(m, height=350, use_container_width=True)

            # 3. ROUTE BREAKDOWN (RESTORED)
            st.markdown("### Route Details")
            st.markdown('<div class="route-container">', unsafe_allow_html=True)
            for i, leg in enumerate(data['legs']):
                theme = "leg-land" if leg['type'] == "land" else "leg-sea"
                icon_bg = "icon-land" if
