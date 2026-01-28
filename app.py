import streamlit as st
import pandas as pd
import requests
import polyline
import textwrap
import io
import time
import gc  # Garbage Collector for memory management
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
import os

# --- 1. CONFIGURATION & INITIALIZATION ---
st.set_page_config(page_title="MyCArbon Route Analytics", layout="wide")
st.markdown("<style>[data-testid='stSidebar'] {display: none;}</style>", unsafe_allow_html=True)

# Initialize session state variables
if 'journey_data' not in st.session_state:
    st.session_state.journey_data = None
if 'bulk_results' not in st.session_state:
    st.session_state.bulk_results = pd.DataFrame()

# --- 2. CSS STYLING ---
st.markdown("""
<style>
    /* Global Background */
    .stApp {
        background-color: #0f172a;
        color: #f8fafc;
    }

    /* Modern Pro Card */
    .react-card {
        background: rgba(30, 41, 59, 0.7);
        backdrop-filter: blur(10px);
        border: 1px solid rgba(255, 255, 255, 0.1);
        border-radius: 1.25rem;
        padding: 2rem;
        box-shadow: 0 20px 25px -5px rgba(0, 0, 0, 0.2);
        margin-bottom: 2rem;
    }

    /* Glow Text for Kilometers */
    .text-grad-sky {
        background: linear-gradient(to right, #38bdf8, #818cf8);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-size: 3rem;
        font-weight: 800;
        text-shadow: 0 0 20px rgba(56, 189, 248, 0.3);
    }

    /* Tab Styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 24px;
        background-color: transparent;
    }

    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: rgba(255, 255, 255, 0.05);
        border-radius: 10px 10px 0px 0px;
        color: #94a3b8;
        padding: 0 20px;
    }

    .stTabs [aria-selected="true"] {
        background-color: rgba(99, 102, 241, 0.2);
        color: #6366f1 !important;
        border-bottom: 2px solid #6366f1 !important;
    }

    /* Custom Scrollbar */
    ::-webkit-scrollbar {
        width: 8px;
    }
    ::-webkit-scrollbar-track {
        background: #0f172a;
    }
    ::-webkit-scrollbar-thumb {
        background: #334155;
        border-radius: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. LOGIC ENGINES ---
def clean_location(raw):
    """
    Robust location cleaning that handles abbreviations (UK -> United Kingdom)
    and strips unnecessary address details.
    """
    geolocator = Nominatim(user_agent="route_pro_v8_chunked")
    
    # Expand common abbreviations
    corrections = {
        "UK": "United Kingdom", "USA": "United States", "UAE": "United Arab Emirates",
        "HK": "Hong Kong", "NZ": "New Zealand", "PH": "Philippines", "SG": "Singapore",
        "DE": "Germany", "FR": "France", "CN": "China", "JP": "Japan", "KR": "South Korea"
    }
    
    search_query = str(raw)
    for abbr, full in corrections.items():
        if f" {abbr}" in search_query or search_query.endswith(abbr) or search_query == abbr:
            search_query = search_query.replace(abbr, full)

    try:
        # Respect API limits with delay
        time.sleep(1.2) 
        
        # Try full clean query
        loc = geolocator.geocode(search_query, addressdetails=True, timeout=10)
        
        # Fallback: If not found, split by comma and try just the first part (City) + Last part (Country)
        if not loc and "," in search_query:
            parts = search_query.split(",")
            fallback_query = f"{parts[0]}, {parts[-1]}"
            loc = geolocator.geocode(fallback_query, addressdetails=True, timeout=10)

        if loc:
            d = loc.raw['address']
            clean = f"{d.get('city') or d.get('town') or d.get('village') or d.get('suburb') or ''}, {d.get('country') or ''}".strip(", ")
            if len(clean) < 3: clean = d.get('country') or search_query
            return loc.latitude, loc.longitude, clean
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

    legs = []
    breakdown = {"land": 0, "air": 0, "sea": 0}
    
    if m.lower() == 'land':
        try:
            url = f"http://router.project-osrm.org/route/v1/driving/{n_o},{l_o};{n_d},{l_d}?overview=full"
            r = requests.get(url, timeout=5).json()
            dist = r['routes'][0]['distance']/1000.0
            coords = polyline.decode(r['routes'][0]['geometry'])
        except:
            dist = geodesic((l_o, n_o), (l_d, n_d)).kilometers * 1.3
            coords = [(l_o, n_o), (l_d, n_d)]
            
        legs.append({"from": c_o, "to": c_d, "dist": dist, "icon": "🚗", "type": "land", "desc": "Land Travel", "coords": coords})
        breakdown['land'] = dist
    else:
        hubs = db_p if m.lower() == 'sea' else db_a
        hubs['t1'] = (hubs['lat'] - l_o)**2 + (hubs['lon'] - n_o)**2
        h1 = hubs.loc[hubs['t1'].idxmin()]
        hubs['t2'] = (hubs['lat'] - l_d)**2 + (hubs['lon'] - n_d)**2
        h2 = hubs.loc[hubs['t2'].idxmin()]
        
        d1 = geodesic((l_o, n_o), (h1['lat'], h1['lon'])).kilometers * 1.2
        d2 = geodesic((h1['lat'], h1['lon']), (h2['lat'], h2['lon'])).kilometers
        d3 = geodesic((h2['lat'], h2['lon']), (l_d, n_d)).kilometers * 1.2
        
        legs = [
            {"from": c_o, "to": h1['name'], "dist": d1, "icon": "🚗", "type": "land", "desc": "Land Travel", "coords": [(l_o, n_o), (h1['lat'], h1['lon'])]},
            {"from": h1['name'], "to": h2['name'], "dist": d2, "icon": "🚢" if m.lower()=='sea' else "✈️", "type": "sea", "desc": f"{m.title()} Travel", "coords": [(h1['lat'], h1['lon']), (h2['lat'], h2['lon'])]},
            {"from": h2['name'], "to": c_d, "dist": d3, "icon": "🚗", "type": "land", "desc": "Land Travel", "coords": [(h2['lat'], h2['lon']), (l_d, n_d)]}
        ]
        breakdown['land'] = d1 + d3
        breakdown[m.lower()] = d2
    
    total = sum(leg['dist'] for leg in legs)
    hours = total / (65 if m=='land' else (35 if m=='sea' else 800))
    
    return {
        "total_km": total, "total_mi": total*0.62, "time": f"{int(hours)}h {int((hours%1)*60)}m",
        "legs": legs, "clean_o": c_o, "clean_d": c_d, "start": (l_o, n_o), "breakdown": breakdown
    }

# --- 4. UI TABS ---
st.title("🌍 Route Analytics")
t1, t2 = st.tabs(["📍 Single", "📂 Bulk Calculation"])

with t1:
    col_a, col_b = st.columns([1, 1.5])
    with col_a:
        with st.form("f1"):
            orig = st.text_input("Origin", "Beverley, UK")
            dest = st.text_input("Destination", "Sweden")
            mode = st.radio("Mode", ["Air", "Sea", "Land"], horizontal=True)
            if st.form_submit_button("Search"):
                with st.spinner("Calculating..."):
                    st.session_state.journey_data = calculate(orig, dest, mode)
                if not st.session_state.journey_data:
                    st.error("Could not find locations. Try expanding abbreviations.")

    with col_b:
        if st.session_state.journey_data:
            data = st.session_state.journey_data
            bk = data['breakdown']
            l_h = f"<div class='breakdown-box'><div style='color:#34d399'>🚗</div><div>{int(bk['land']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Land</div></div>" if bk['land']>0 else ""
            a_h = f"<div class='breakdown-box'><div style='color:#38bdf8'>✈️</div><div>{int(bk['air']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Air</div></div>" if bk['air']>0 else ""
            s_h = f"<div class='breakdown-box'><div style='color:#818cf8'>🚢</div><div>{int(bk['sea']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Sea</div></div>" if bk['sea']>0 else ""

            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="font-size:14px; color:#cbd5e1; margin-bottom:10px">Journey Summary</div>
                    <div style="display:flex; gap:30px; margin-bottom:15px">
                        <div><div class="text-grad-sky">{int(data['total_km']):,}</div><div style="color:#94a3b8">km</div></div>
                        <div><div class="text-grad-orange">{int(data['total_mi']):,}</div><div style="color:#94a3b8">mi</div></div>
                    </div>
                    <div style="margin-bottom:15px; color:#cbd5e1">⏱️ Est: <span style="color:white; font-weight:600">{data['time']}</span></div>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; border-top:1px solid #334155; padding-top:15px">{l_h}{a_h}{s_h}</div>
                </div>
            """), unsafe_allow_html=True)
            
            m_obj = folium.Map(location=data['start'], zoom_start=4)
            for leg in data['legs']: folium.PolyLine(leg['coords'], color="#3b82f6", weight=4).add_to(m_obj)
            st_folium(m_obj, height=300, use_container_width=True)

            st.markdown("### Route Details")
            st.markdown('<div class="route-container">', unsafe_allow_html=True)
            for i, leg in enumerate(data['legs']):
                theme = "leg-land" if leg['type'] == "land" else "leg-sea"
                icon_bg = "icon-land" if leg['type'] == "land" else "icon-sea"
                st.markdown(textwrap.dedent(f"""
                    <div class="leg-card {theme}">
                        <div style="display:flex; align-items:center;">
                            <div class="icon-box {icon_bg}">{leg['icon']}</div>
                            <div><div style="font-weight:700">Leg {i+1}: {leg['desc']}</div><div style="font-size:0.9rem">{leg['from']} → {leg['to']}</div></div>
                        </div>
                        <div style="text-align:right"><div class="stat-km">{int(leg['dist'])} km</div></div>
                    </div>
                """), unsafe_allow_html=True)
                if i < len(data['legs']) - 1: st.markdown('<div class="connector"><div class="conn-line"></div><div class="conn-arrow">↓</div></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

with t2:
    st.info("Large Datasets: Processing happens in chunks of 50 to prevent crashes. Please keep this tab active.")
    up = st.file_uploader("Upload CSV", type="csv")
    
    if up:
        df = pd.read_csv(up)
        st.write(f"📋 **Total Rows:** {len(df)}")
        st.dataframe(df.head())
        
        chunk_size = 50
        if st.button("🚀 Calculate Batch"):
            all_results = []
            progress_bar = st.progress(0)
            status_text = st.empty()
            
            # CHUNK PROCESSING LOOP
            total_rows = len(df)
            for start_idx in range(0, total_rows, chunk_size):
                end_idx = min(start_idx + chunk_size, total_rows)
                chunk = df.iloc[start_idx:end_idx]
                
                status_text.text(f"Processing rows {start_idx + 1} to {end_idx}...")
                
                chunk_results = []
                for i, row in chunk.iterrows():
                    # Calculate single row
                    j = calculate(str(row[0]), str(row[1]), str(row[2]))
                    
                    # Store Result
                    if j:
                        chunk_results.append({
                            "Origin_Input": row[0], "Dest_Input": row[1],
                            "Resolved_Origin": j['clean_o'], "Resolved_Dest": j['clean_d'],
                            "Total_KM": round(j['total_km'], 1),
                            "Land_KM": round(j['breakdown']['land'], 1),
                            "Air_KM": round(j['breakdown']['air'], 1),
                            "Sea_KM": round(j['breakdown']['sea'], 1),
                            "Est_Time": j['time']
                        })
                    else:
                        chunk_results.append({
                            "Origin_Input": row[0], "Dest_Input": row[1],
                            "Resolved_Origin": "Err", "Resolved_Dest": "Err",
                            "Total_KM": 0, "Land_KM": 0, "Air_KM": 0, "Sea_KM": 0, "Est_Time": "Err"
                        })
                    
                    # Update Progress
                    current_progress = (i + 1) / total_rows
                    progress_bar.progress(current_progress)

                # Append chunk to main results
                all_results.extend(chunk_results)
                
                # MEMORY MANAGEMENT: Clear vars and run garbage collection
                del chunk
                del chunk_results
                gc.collect() 
            
            # FINAL OUTPUT
            final_df = pd.DataFrame(all_results)
            st.session_state.bulk_results = final_df # Save to state
            st.success("✅ Processing Complete!")
            st.dataframe(final_df)
            
            csv = final_df.to_csv(index=False).encode('utf-8')
            st.download_button("💾 Download Results", csv, "bulk_results.csv", "text/csv")



