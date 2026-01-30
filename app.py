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
import math

# --- 1. CONFIGURATION & INITIALIZATION ---
st.set_page_config(page_title="Route Analytics Pro", layout="wide")

# Custom CSS
st.markdown("""
<style>
    /* --- HIDE STREAMLIT BRANDING --- */
    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    header {visibility: hidden;}
    [data-testid="stHeader"] {display: none;}
    [data-testid="stToolbar"] {visibility: hidden;}
    
    /* Global Background */
    .stApp { background-color: #f8fafc; color: #1e293b; margin-top: -50px; }
    
    /* Result Card */
    .react-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border-radius: 1rem; padding: 1.5rem; color: white;
        margin-bottom: 2rem; box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .text-grad-sky { background: linear-gradient(to right, #38bdf8, #67e8f9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.5rem; font-weight: 800; line-height: 1; }
    .text-grad-orange { background: linear-gradient(to right, #fb923c, #fcd34d); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.5rem; font-weight: 800; line-height: 1; }
    
    /* UI Elements */
    .breakdown-box { background: rgba(30, 41, 59, 0.5); border-radius: 0.5rem; padding: 0.75rem; border: 1px solid rgba(255,255,255,0.1); color: #cbd5e1; font-weight: 600; }
    .route-container { background-color: #ffffff; padding: 1.25rem; border-radius: 1rem; color: #1e293b; border: 1px solid #e2e8f0; }
    .leg-card { display: flex; justify-content: space-between; align-items: center; padding: 1rem; border-radius: 0.75rem; border: 1px solid #e2e8f0; margin-bottom: 8px; background: white; position: relative; z-index: 2; }
    .leg-land { border-left: 5px solid #10b981; }
    .leg-sea { border-left: 5px solid #3b82f6; }
    .icon-box { width: 40px; height: 40px; border-radius: 50%; display: flex; align-items: center; justify-content: center; font-size: 1.2rem; margin-right: 12px; }
    .icon-land { background: #ecfdf5; color: #10b981; }
    .icon-sea { background: #eff6ff; color: #3b82f6; }
    .connector { display: flex; justify-content: center; align-items: center; height: 24px; position: relative; margin: -2px 0; }
    .conn-line { position: absolute; width: 2px; height: 100%; background: #e2e8f0; left: calc(50% - 1px); z-index: 0; }
    .conn-arrow { z-index: 1; background: #ffffff; color: #94a3b8; padding: 0 4px; font-size: 0.8rem; }
    div[data-baseweb="input"] { background-color: white !important; }
</style>
""", unsafe_allow_html=True)

# Session States
if 'journey_data' not in st.session_state: st.session_state.journey_data = None
if 'multi_legs' not in st.session_state: st.session_state.multi_legs = [{"id": 0, "val": ""}, {"id": 1, "val": ""}]
if 'multi_res' not in st.session_state: st.session_state.multi_res = None  # NEW: To stop results disappearing

# --- 2. LOGIC ENGINES ---
@st.cache_data
def load_hubs():
    p, a = pd.DataFrame(), pd.DataFrame()
    try:
        p_air = 'AirportLists.csv' if os.path.exists('AirportLists.csv') else 'PortDistanceApp/AirportLists.csv'
        p_sea = 'SeaportList.csv' if os.path.exists('SeaportList.csv') else 'PortDistanceApp/SeaportList.csv'
        a = pd.read_csv(p_air, header=None, encoding='latin1').rename(columns={1:'name', 4:'iata', 6:'lat', 7:'lon'})
        p = pd.read_csv(p_sea, encoding='latin1')
        p.rename(columns={'port_name':'name','latitude':'lat','longitude':'lon'}, inplace=True, errors='ignore')
    except: pass
    return p, a

def clean_location(raw):
    search_query = str(raw).strip()
    # Check IATA
    if len(search_query) == 3 and search_query.isalpha():
        _, db_a = load_hubs()
        match = db_a[db_a['iata'] == search_query.upper()]
        if not match.empty:
            return match.iloc[0]['lat'], match.iloc[0]['lon'], f"{match.iloc[0]['name']} ({search_query.upper()})"
    # Standard Geocode
    geolocator = Nominatim(user_agent="route_pro_final_v17")
    corrections = {"UK": "United Kingdom", "USA": "United States", "PH": "Philippines"}
    for abbr, full in corrections.items():
        if search_query.endswith(abbr) or f" {abbr}" in search_query:
            search_query = search_query.replace(abbr, full)
    for attempt in range(3):
        try:
            time.sleep(1.2 + attempt)
            loc = geolocator.geocode(search_query, addressdetails=True, timeout=10)
            if loc:
                d = loc.raw['address']
                clean = f"{d.get('city') or d.get('town') or d.get('state') or ''}, {d.get('country') or ''}".strip(", ")
                return loc.latitude, loc.longitude, clean or search_query
        except: continue
    return None, None, None

def get_curve_points(start, end):
    lat1, lon1 = math.radians(start[0]), math.radians(start[1])
    lat2, lon2 = math.radians(end[0]), math.radians(end[1])
    d = 2 * math.asin(math.sqrt(math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2))
    if d == 0: return [start, end]
    points = []
    for i in range(31):
        f = i / 30
        a = math.sin((1 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(lat1) * math.cos(lon1) + b * math.cos(lat2) * math.cos(lon2)
        y = a * math.cos(lat1) * math.sin(lon1) + b * math.cos(lat2) * math.sin(lon2)
        z = a * math.sin(lat1) + b * math.sin(lat2)
        points.append((math.degrees(math.atan2(z, math.sqrt(x**2 + y**2))), math.degrees(math.atan2(y, x))))
    return points

def calculate(o, d, m):
    db_p, db_a = load_hubs()
    l_o, n_o, c_o = clean_location(o)
    l_d, n_d, c_d = clean_location(d)
    if l_o is None or l_d is None: return None

    legs, bk = [], {"land": 0, "air": 0, "sea": 0}
    if m.lower() == 'land':
        try:
            url = f"http://router.project-osrm.org/route/v1/driving/{n_o},{l_o};{n_d},{l_d}?overview=full"
            r = requests.get(url, timeout=5).json()
            dist = r['routes'][0]['distance']/1000.0
            coords = polyline.decode(r['routes'][0]['geometry'])
        except:
            dist = geodesic((l_o, n_o), (l_d, n_d)).kilometers * 1.3
            coords = [(l_o, n_o), (l_d, n_d)]
        legs.append({"from": c_o, "to": c_d, "dist": dist, "icon": "🚗", "type": "land", "desc": "Road Route", "coords": coords})
        bk['land'] = dist
    else:
        hubs = db_p if m.lower() == 'sea' else db_a
        hubs['t1'] = (hubs['lat'] - l_o)**2 + (hubs['lon'] - n_o)**2
        h1 = hubs.loc[hubs['t1'].idxmin()]
        hubs['t2'] = (hubs['lat'] - l_d)**2 + (hubs['lon'] - n_d)**2
        h2 = hubs.loc[hubs['t2'].idxmin()]
        d1 = geodesic((l_o, n_o), (h1['lat'], h1['lon'])).kilometers * 1.2
        d2 = geodesic((h1['lat'], h1['lon']), (h2['lat'], h2['lon'])).kilometers
        d3 = geodesic((h2['lat'], h2['lon']), (l_d, n_d)).kilometers * 1.2
        curve_coords = get_curve_points((h1['lat'], h1['lon']), (h2['lat'], h2['lon']))
        legs = [
            {"from": c_o, "to": h1['name'], "dist": d1, "icon": "🚗", "type": "land", "desc": "To Hub", "coords": [(l_o, n_o), (h1['lat'], h1['lon'])]},
            {"from": h1['name'], "to": h2['name'], "dist": d2, "icon": "🚢" if m.lower()=='sea' else "✈️", "type": "sea", "desc": "Main Transit", "coords": curve_coords},
            {"from": h2['name'], "to": c_d, "dist": d3, "icon": "🚗", "type": "land", "desc": "To Final", "coords": [(h2['lat'], h2['lon']), (l_d, n_d)]}
        ]
        bk['land'], bk[m.lower()] = (d1+d3), d2
    
    total = sum(leg['dist'] for leg in legs)
    hours = total / (65 if m=='land' else (35 if m=='sea' else 800))
    return {"total_km": total, "total_mi": total*0.62, "time": f"{int(hours)}h", "legs": legs, "clean_o": c_o, "clean_d": c_d, "start": (l_o, n_o), "breakdown": bk}

# --- 3. UI TABS ---
t1, t2, t3 = st.tabs(["📍 Single Journey", "🔗 Multi-Leg", "📂 Bulk Processing"])

# TAB 1: SINGLE
with t1:
    cola, colb = st.columns([1, 1.5])
    with cola:
        st.subheader("Point-to-Point")
        with st.form("single_form"):
            o_in = st.text_input("Origin", "XRY")
            d_in = st.text_input("Destination", "MAD")
            m_in = st.radio("Mode", ["Air", "Sea", "Land"], horizontal=True)
            if st.form_submit_button("Calculate"):
                with st.spinner("Processing..."):
                    st.session_state.journey_data = calculate(o_in, d_in, m_in)
    with colb:
        if st.session_state.journey_data:
            data = st.session_state.journey_data
            bk = data['breakdown']
            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="color:#cbd5e1; font-size:0.85rem; font-weight:600; margin-bottom:10px;">TOTAL DISTANCE</div>
                    <div style="display:flex; gap:40px; margin-bottom:15px">
                        <div><div class="text-grad-sky">{int(data['total_km']):,}</div><div style="color:#94a3b8; font-size:12px">KM</div></div>
                        <div><div class="text-grad-orange">{int(data['total_mi']):,}</div><div style="color:#94a3b8; font-size:12px">MILES</div></div>
                    </div>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; border-top:1px solid rgba(255,255,255,0.1); padding-top:15px">
                        <div class="breakdown-box">🚗 {int(bk['land']):,} km</div>
                        <div class="breakdown-box">✈️ {int(bk['air']):,} km</div>
                        <div class="breakdown-box">🚢 {int(bk['sea']):,} km</div>
                    </div>
                </div>
            """), unsafe_allow_html=True)
            m = folium.Map(location=data['start'], zoom_start=4)
            for leg in data['legs']: folium.PolyLine(leg['coords'], color="#2563eb", weight=4).add_to(m)
            st_folium(m, height=350, use_container_width=True)
            
            st.markdown("### Route Details")
            st.markdown('<div class="route-container">', unsafe_allow_html=True)
            for i, leg in enumerate(data['legs']):
                theme, icon_bg = ("leg-land", "icon-land") if leg['type'] == "land" else ("leg-sea", "icon-sea")
                st.markdown(textwrap.dedent(f"""
                    <div class="leg-card {theme}">
                        <div style="display:flex; align-items:center;">
                            <div class="icon-box {icon_bg}">{leg['icon']}</div>
                            <div><div style="font-weight:700">Leg {i+1}: {leg['desc']}</div><div style="font-size:0.9rem">{leg['from']} → {leg['to']}</div></div>
                        </div>
                        <div style="font-weight:700">{int(leg['dist'])} km</div>
                    </div>
                """), unsafe_allow_html=True)
                if i < len(data['legs']) - 1: st.markdown('<div class="connector"><div class="conn-line"></div><div class="conn-arrow">↓</div></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

# TAB 2: MULTI-LEG (FIXED PERSISTENCE)
with t2:
    col_l, col_r = st.columns([1, 1.5])
    with col_l:
        st.subheader("Build Itinerary")
        st.markdown("**🚀 Quick Parse:** Paste a string like `XRY>MAD>LHR>MAD` below:")
        quick_str = st.text_input("Route String", placeholder="e.g. XRY-MAD-LHR", label_visibility="collapsed")
        if st.button("Parse String"):
            if quick_str:
                import re
                parts = re.split(r'[>\-,]', quick_str)
                st.session_state.multi_legs = [{"id": i, "val": p.strip()} for i, p in enumerate(parts) if p.strip()]
                st.rerun()

        st.divider()
        st.write("**Or build manually:**")

        with st.form("multi_leg_form"):
            for i, leg in enumerate(st.session_state.multi_legs):
                leg['val'] = st.text_input(f"Stop {i+1}", value=leg['val'], key=f"leg_{i}")
            c1, c2, c3 = st.columns(3)
            with c1: 
                if st.form_submit_button("➕ Add Stop"): 
                    st.session_state.multi_legs.append({"id": len(st.session_state.multi_legs), "val": ""})
                    st.rerun()
            with c2: 
                if st.form_submit_button("➖ Remove"): 
                    if len(st.session_state.multi_legs) > 2: st.session_state.multi_legs.pop()
                    st.rerun()
            with c3: calc_multi = st.form_submit_button("🚀 Calculate")
            mode_multi = st.radio("Primary Mode", ["Air", "Sea", "Land"], horizontal=True)

    with col_r:
        if calc_multi:
            stops = [l['val'] for l in st.session_state.multi_legs if l['val'].strip() != ""]
            if len(stops) < 2:
                st.error("Please enter at least 2 valid locations.")
            else:
                total_km = 0
                legs_data = []
                map_center = None
                
                with st.spinner("Calculating multi-leg itinerary..."):
                    for i in range(len(stops)-1):
                        orig, dest = stops[i], stops[i+1]
                        res = calculate(orig, dest, mode_multi)
                        if res:
                            total_km += res['total_km']
                            legs_data.append({
                                "seq": i+1, "from": res['clean_o'], "to": res['clean_d'], 
                                "dist": res['total_km'], "coords": res['legs'], "start": res['start']
                            })
                            if i == 0: map_center = res['start']
                        else:
                            st.error(f"Could not resolve: {orig} -> {dest}")
                
                # SAVE TO SESSION STATE TO PREVENT DISAPPEARING
                if legs_data:
                    st.session_state.multi_res = {"total": total_km, "legs": legs_data, "center": map_center}
        
        # DISPLAY RESULTS FROM SESSION STATE
        if st.session_state.multi_res:
            res = st.session_state.multi_res
            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="color: #cbd5e1; font-size: 0.85rem; font-weight: 600; margin-bottom: 10px;">ITINERARY TOTAL</div>
                    <div style="display:flex; gap:40px;">
                        <div><div class="text-grad-sky">{int(res['total']):,}</div><div style="color:#94a3b8; font-size:12px">KILOMETERS</div></div>
                        <div><div class="text-grad-orange">{int(res['total']*0.62):,}</div><div style="color:#94a3b8; font-size:12px">MILES</div></div>
                    </div>
                </div>
            """), unsafe_allow_html=True)
            
            m_multi = folium.Map(location=res['center'], zoom_start=3)
            for leg in res['legs']:
                for segment in leg['coords']:
                    color = "#10b981" if segment['type'] == 'land' else "#3b82f6"
                    folium.PolyLine(segment['coords'], color=color, weight=3, opacity=0.8).add_to(m_multi)
                folium.Marker(leg['start'], popup=leg['from'], icon=folium.Icon(color='blue', icon='info-sign')).add_to(m_multi)
            st_folium(m_multi, height=350, use_container_width=True)
            
            st.markdown("### Itinerary Breakdown")
            st.markdown('<div class="route-container">', unsafe_allow_html=True)
            for leg in res['legs']:
                st.markdown(textwrap.dedent(f"""
                    <div class="leg-card leg-sea">
                        <div style="display:flex; align-items:center;">
                            <div class="icon-box icon-sea">{leg['seq']}</div>
                            <div><div style="font-weight:700">{leg['from']}</div><div style="font-size:0.9rem">to {leg['to']}</div></div>
                        </div>
                        <div style="font-weight:700">{int(leg['dist']):,} km</div>
                    </div>
                """), unsafe_allow_html=True)
                if leg['seq'] < len(res['legs']): st.markdown('<div class="connector"><div class="conn-line"></div><div class="conn-arrow">↓</div></div>', unsafe_allow_html=True)
            st.markdown('</div>', unsafe_allow_html=True)

# TAB 3: BULK
with t3:
    st.markdown("### Bulk Operations")
    template = pd.DataFrame({'Origin': ['Minster House, 23 Flemingate, Beverley, UK'], 'Destination': ['26491, Sweden'], 'Mode': ['Air']})
    st.download_button("📥 Download Template", template.to_csv(index=False), "template.csv", "text/csv")
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
