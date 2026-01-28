import streamlit as st
import pandas as pd
import requests
import polyline
import textwrap
import io
import time
from geopy.distance import geodesic
from geopy.geocoders import Nominatim
import folium
from streamlit_folium import st_folium
import os

# --- 1. CONFIGURATION ---
st.set_page_config(page_title="MyCarbon Route Analytics", layout="wide")
st.markdown("<style>[data-testid='stSidebar'] {display: none;}</style>", unsafe_allow_html=True)

# --- 2. CSS STYLING ---
st.markdown("""
<style>
    /* Main Result Card */
    .react-card {
        background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #0f172a 100%);
        border-radius: 1rem; padding: 1.5rem; color: white; margin-bottom: 2rem;
        box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.1);
    }
    .text-grad-sky { background: linear-gradient(to right, #38bdf8, #67e8f9); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.5rem; font-weight: 700; }
    .text-grad-orange { background: linear-gradient(to right, #fb923c, #fcd34d); -webkit-background-clip: text; -webkit-text-fill-color: transparent; font-size: 2.5rem; font-weight: 700; }
    .breakdown-box { background: rgba(30, 41, 59, 0.5); border-radius: 0.5rem; padding: 0.75rem; border: 1px solid rgba(255,255,255,0.1); text-align: left; }

    /* NEW ROUTE BREAKDOWN UI (Matches Target Screenshot) */
    .route-container {
        background-color: #f8fafc;
        padding: 1rem 0;
        border-radius: 1rem;
    }

    /* Card Base Style */
    .leg-card {
        display: flex;
        justify-content: space-between;
        align-items: center;
        padding: 1.25rem;
        border-radius: 1rem;
        border: 1px solid;
        position: relative;
        z-index: 2;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05);
    }

    /* Land Theme (Green) */
    .leg-land {
        background-color: #ecfdf5; /* bg-green-50 */
        border-color: #6ee7b7; /* border-green-300 */
        color: #065f46; /* text-green-800 */
    }
    .icon-box-land { background-color: #10b981; color: white; } /* bg-green-500 */

    /* Sea/Air Theme (Blue/Purple) */
    .leg-sea {
        background-color: #eff6ff; /* bg-blue-50 */
        border-color: #93c5fd; /* border-blue-300 */
        color: #1e40af; /* text-blue-800 */
    }
    .icon-box-sea { background-color: #6366f1; color: white; } /* bg-indigo-500 */

    /* Content Styling */
    .icon-box {
        width: 54px; height: 54px; border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.75rem; margin-right: 1.25rem;
        flex-shrink: 0; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .leg-details { flex-grow: 1; }
    .leg-title { font-weight: 700; font-size: 1.15rem; margin-bottom: 0.35rem; }
    .leg-route { font-size: 0.95rem; margin-bottom: 0.25rem; font-weight: 500; }
    .leg-via { font-size: 0.85rem; opacity: 0.8; }
    .leg-stats { text-align: right; min-width: 110px; }
    .stat-km { font-size: 1.35rem; font-weight: 800; color: #111827; line-height: 1.2;}
    .stat-muted { font-size: 0.85rem; color: #6b7280; font-weight: 500;}

    /* Connector Arrow */
    .connector-container {
        display: flex; justify-content: center; align-items: center;
        height: 36px; position: relative; margin: -2px 0;
    }
    .connector-line {
        position: absolute; height: 100%; width: 3px; background-color: #e5e7eb; z-index: 0; left: calc(50% - 1.5px);
    }
    .connector-arrow {
        z-index: 1; color: #9ca3af; font-size: 1.1rem; background: #f8fafc; padding: 2px 0;
    }
</style>
""", unsafe_allow_html=True)

# --- 3. SMART LOCATION CLEANER ---
def clean_location_string(raw_address):
    """Resolves specific addresses (e.g., 'Minster House...') to 'City, Country'."""
    geolocator = Nominatim(user_agent="route_pro_cleaner_v3")
    try:
        location = geolocator.geocode(raw_address, addressdetails=True, timeout=10)
        if location:
            addr = location.raw['address']
            # Prioritize: Town/City -> County -> Country
            parts = [
                addr.get('city') or addr.get('town') or addr.get('village') or addr.get('suburb'),
                addr.get('country')
            ]
            clean_str = ", ".join([p for p in parts if p])
            return location.latitude, location.longitude, clean_str
    except:
        pass
    return None, None, None

# --- 4. CALCULATION ENGINE ---
@st.cache_data
def load_hubs():
    ports, airports = pd.DataFrame(), pd.DataFrame()
    try:
        p_air = 'AirportLists.csv' if os.path.exists('AirportLists.csv') else 'PortDistanceApp/AirportLists.csv'
        p_sea = 'SeaportList.csv' if os.path.exists('SeaportList.csv') else 'PortDistanceApp/SeaportList.csv'
        
        airports = pd.read_csv(p_air, header=None, encoding='latin1')
        airports.rename(columns={1: 'name', 6: 'lat', 7: 'lon'}, inplace=True)
        ports = pd.read_csv(p_sea, encoding='latin1')
        ports.columns = ports.columns.str.strip().str.lower()
        ports.rename(columns={'port_name': 'name', 'latitude':'lat', 'longitude':'lon'}, inplace=True, errors='ignore')
    except: pass
    return ports, airports

def calculate_journey(origin, dest, mode):
    ports_db, airports_db = load_hubs()
    
    # 1. Smart Resolve (Fixes "0 distance" issue)
    time.sleep(1.2) # Rate limiting
    lat_o, lon_o, clean_o = clean_location_string(origin)
    lat_d, lon_d, clean_d = clean_location_string(dest)
    
    if lat_o is None or lat_d is None: return None

    c_o, c_d = (lat_o, lon_o), (lat_d, lon_d)
    breakdown = {"land": 0, "air": 0, "sea": 0}
    
    # 2. Routing Logic
    if mode.lower() == 'land':
        try:
            url = f"http://router.project-osrm.org/route/v1/driving/{lon_o},{lat_o};{lon_d},{lat_d}?overview=full"
            r = requests.get(url, timeout=5).json()
            dist = r['routes'][0]['distance']/1000.0
            coords = polyline.decode(r['routes'][0]['geometry'])
        except:
            dist = geodesic(c_o, c_d).kilometers * 1.3
            coords = [c_o, c_d]
        legs = [{"from": clean_o, "to": clean_d, "dist": dist, "icon": "🚗", "coords": coords, "desc": "Driving Route"}]
        breakdown['land'] = dist
    else:
        db = ports_db if mode.lower() == 'sea' else airports_db
        # Find nearest hubs
        db['tmp'] = (db['lat'] - lat_o)**2 + (db['lon'] - lon_o)**2
        h1 = db.loc[db['tmp'].idxmin()]
        db['tmp'] = (db['lat'] - lat_d)**2 + (db['lon'] - lon_d)**2
        h2 = db.loc[db['tmp'].idxmin()]
        
        d1 = geodesic(c_o, (h1['lat'], h1['lon'])).kilometers * 1.2
        d2 = geodesic((h1['lat'], h1['lon']), (h2['lat'], h2['lon'])).kilometers
        d3 = geodesic((h2['lat'], h2['lon']), c_d).kilometers * 1.2
        
        legs = [
            {"from": clean_o, "to": h1['name'], "dist": d1, "icon": "🚗", "coords": [c_o, (h1['lat'], h1['lon'])], "desc": "Land Travel"},
            {"from": h1['name'], "to": h2['name'], "dist": d2, "icon": "🚢" if mode.lower()=='sea' else "✈️", "coords": [(h1['lat'], h1['lon']), (h2['lat'], h2['lon'])], "desc": f"{mode.title()} Travel"},
            {"from": h2['name'], "to": clean_d, "dist": d3, "icon": "🚗", "coords": [(h2['lat'], h2['lon']), c_d], "desc": "Land Travel"}
        ]
        breakdown['land'], breakdown[mode.lower()] = (d1+d3), d2

    total_km = sum(l['dist'] for l in legs)
    speed = 800 if mode.lower() == 'air' else (35 if mode.lower() == 'sea' else 65)
    hours = (total_km / speed) + (3 if mode.lower() != 'land' else 0)
    
    return {
        "total_km": total_km, "total_miles": total_km*0.6213, 
        "time": f"{int(hours)}h {int((hours%1)*60)}m", 
        "clean_o": clean_o, "clean_d": clean_d,
        "breakdown": breakdown, "legs": legs, "waypoints": [c_o, c_d]
    }

# --- 5. UI TABS ---
st.title("🌍 Route Analytics")
t1, t2 = st.tabs(["📍 Single Journey", "📂 Bulk Processing"])

with t1:
    col_in, col_out = st.columns([1, 1.5])
    with col_in:
        with st.form("single"):
            o_input = st.text_input("Origin Address", "Minster House, 23 Flemingate, Beverley, UK")
            d_input = st.text_input("Destination Address", "26491, Sweden")
            m_input = st.radio("Mode", ["Air", "Sea", "Land"], horizontal=True)
            if st.form_submit_button("Calculate"):
                res = calculate_journey(o_input, d_input, m_input)
                if res: 
                    st.session_state.journey_data = res
                    st.success(f"Resolved: {res['clean_o']} ➔ {res['clean_d']}")
                else: 
                    st.error("Address Not Found. Please simplify.")

    with col_out:
        if st.session_state.journey_data:
            data = st.session_state.journey_data
            bk = data['breakdown']
            
            # 1. GENERATE MAIN CARD HTML
            l_h = f"<div class='breakdown-box'><div style='color:#34d399'>🚗</div><div>{int(bk['land']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Land</div></div>" if bk['land']>0 else ""
            a_h = f"<div class='breakdown-box'><div style='color:#38bdf8'>✈️</div><div>{int(bk['air']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Air</div></div>" if bk['air']>0 else ""
            s_h = f"<div class='breakdown-box'><div style='color:#818cf8'>🚢</div><div>{int(bk['sea']):,} km</div><div style='font-size:10px; color:#cbd5e1'>Sea</div></div>" if bk['sea']>0 else ""
            
            st.markdown(textwrap.dedent(f"""
                <div class="react-card">
                    <div style="font-size:14px; margin-bottom:10px; color:#cbd5e1;">Journey Summary</div>
                    <div style="display:flex; gap:30px; margin-bottom:15px;">
                        <div><div class="text-grad-sky">{int(data['total_km']):,}</div><div style="color:#94a3b8; font-size:12px">kilometers</div></div>
                        <div><div class="text-grad-orange">{int(data['total_miles']):,}</div><div style="color:#94a3b8; font-size:12px">miles</div></div>
                    </div>
                    <div style="margin-bottom:15px; color:#cbd5e1">⏱️ Est. Time: <span style="color:white; font-weight:600">{data['time']}</span></div>
                    <div style="display:grid; grid-template-columns: repeat(3, 1fr); gap:10px; border-top:1px solid #334155; padding-top:15px">
                        {l_h}{a_h}{s_h}
                    </div>
                </div>
            """), unsafe_allow_html=True)
            
            # 2. GENERATE MAP
            m_obj = folium.Map(location=data['waypoints'][0], zoom_start=4)
            for leg in data['legs']: folium.PolyLine(leg['coords'], color="#3b82f6", weight=4).add_to(m_obj)
            st_folium(m_obj, height=300, use_container_width=True)

            # 3. NEW UI: ROUTE BREAKDOWN (Matches Screenshot)
            st.markdown("### Route Breakdown")
            st.markdown('<div class="route-container">', unsafe_allow_html=True) # Container start

            for i, leg in enumerate(data['legs']):
                # Determine Theme based on icon
                is_land = leg['icon'] == "🚗"
                theme_class = "leg-land" if is_land else "leg-sea"
                icon_class = "icon-box-land" if is_land else "icon-box-sea"
                via_text = "via Car/Truck" if is_land else ("via Ship/Ferry" if leg['icon'] == "🚢" else "via Airplane")
                
                # Calculate leg stats
                km = int(leg['dist'])
                miles = int(km * 0.621371)
                speed = 65 if is_land else (35 if leg['icon'] == "🚢" else 800)
                hours = km / speed
                time_str = f"{int(hours)}h {int((hours%1)*60)}m"

                # Card HTML
                card_html = textwrap.dedent(f"""
                    <div class="leg-card {theme_class}">
                        <div style="display:flex; align-items:center; flex-grow:1;">
                            <div class="icon-box {icon_class}">{leg['icon']}</div>
                            <div class="leg-details">
                                <div class="leg-title">Leg {i+1}: {leg['desc']}</div>
                                <div class="leg-route">{leg['from']} → {leg['to']}</div>
                                <div class="leg-via">{via_text}</div>
                            </div>
                        </div>
                        <div class="leg-stats">
                            <div class="stat-km">{km:,} km</div>
                            <div class="stat-muted">{miles:,} mi</div>
                            <div class="stat-muted">{time_str}</div>
                        </div>
                    </div>
                """).strip()
                st.markdown(card_html, unsafe_allow_html=True)

                # Connector HTML (if not last item)
                if i < len(data['legs']) - 1:
                    st.markdown(textwrap.dedent("""
                        <div class="connector-container">
                            <div class="connector-line"></div>
                            <div class="connector-arrow">↓</div>
                        </div>
                    """).strip(), unsafe_allow_html=True)

            st.markdown('</div>', unsafe_allow_html=True) # Container end

with t2:
    st.info("Upload CSV. 'Smart Resolver' will clean specific addresses automatically.")
    template = pd.DataFrame({'Origin': ['Minster House, 23 Flemingate, Beverley, UK'], 'Destination': ['26491, Sweden'], 'Mode': ['Air']})
    st.download_button("📥 Download Template", template.to_csv(index=False), "template.csv")
    
    file = st.file_uploader("Upload CSV", type=["csv"])
    if file:
        df = pd.read_csv(file)
        st.write("📋 **Preview Uploaded Data:**")
        st.dataframe(df.head(), use_container_width=True)
        
        if st.button("🚀 Run Smart Calculation"):
            final_res = []
            progress = st.progress(0)
            for i, row in df.iterrows():
                j = calculate_journey(str(row['Origin']), str(row['Destination']), str(row['Mode']))
                if j: final_res.append({"Resolved_O": j['clean_o'], "Resolved_D": j['clean_d'], "Total_KM": round(j['total_km'],1), "Land_KM": round(j['breakdown']['land'],1), "Air_KM": round(j['breakdown']['air'],1), "Sea_KM": round(j['breakdown']['sea'],1)})
                else: final_res.append({"Resolved_O": "Not Found", "Resolved_D": "Not Found", "Total_KM": 0, "Land_KM": 0, "Air_KM": 0, "Sea_KM": 0})
                progress.progress((i+1)/len(df))
            
            output_df = pd.concat([df, pd.DataFrame(final_res)], axis=1)
            st.success("✅ Batch complete!")
            st.dataframe(output_df, use_container_width=True)
            st.download_button("💾 Download Results", output_df.to_csv(index=False), "results.csv")