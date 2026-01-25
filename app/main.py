"""
Renewable Energy Simulator - Main Application Entry Point

Multi-page Streamlit application for renewable energy simulation and analysis.
"""
import streamlit as st
import sys
from pathlib import Path

# Add src to path for imports
src_path = Path(__file__).parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

# Page config (must be first Streamlit command)
st.set_page_config(
    page_title="Renewable Energy Simulator Pro",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom CSS for professional styling
st.markdown("""
<style>
    /* Main container styling */
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 2rem;
    }
    
    /* Metric card styling */
    .stMetric {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        border-radius: 12px;
        padding: 15px;
        color: white;
    }
    
    .stMetric label {
        color: rgba(255, 255, 255, 0.8) !important;
    }
    
    .stMetric [data-testid="stMetricValue"] {
        color: white !important;
    }
    
    /* Sidebar styling */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f1419 0%, #1a2332 100%);
    }
    
    /* Tab styling */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
    }
    
    .stTabs [data-baseweb="tab"] {
        border-radius: 8px;
        padding: 10px 20px;
    }
    
    /* Button styling */
    .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #339af0 0%, #1c7ed6 100%);
        border: none;
        border-radius: 8px;
        padding: 10px 24px;
    }
    
    /* Header with gradient */
    h1 {
        background: linear-gradient(135deg, #339af0 0%, #51cf66 100%);
        -webkit-background-clip: text;
        -webkit-text-fill-color: transparent;
        font-weight: 700;
    }
</style>
""", unsafe_allow_html=True)

# Main page content
st.title("⚡ Renewable Energy Simulator Pro")
st.markdown("**Professional-grade simulation platform for utility-scale renewable energy projects**")

# Feature overview
st.markdown("---")

col1, col2, col3, col4 = st.columns(4)

with col1:
    st.markdown("""
    ### ☀️ Solar PV
    - PVsyst-style simulation
    - Auto-sizing from land area
    - 13-stage loss waterfall
    - PVGIS TMY integration
    """)

with col2:
    st.markdown("""
    ### 💨 Wind Farm
    - WindPro-style simulation
    - Turbine library
    - Wake effect modeling
    - 6-stage loss waterfall
    """)

with col3:
    st.markdown("""
    ### 🔋 Battery Storage
    - LFP/NMC chemistry
    - Multiple sizing strategies
    - SoC tracking
    - Degradation modeling
    """)

with col4:
    st.markdown("""
    ### 💰 Financial Analysis
    - LCoE calculator
    - Floor PPA (NPV=0)
    - Morocco tariffs
    - Multi-objective optimization
    """)

st.markdown("---")

# Quick start section
st.subheader("🚀 Quick Start")

col1, col2 = st.columns(2)

with col1:
    st.markdown("""
    #### Getting Started
    1. Navigate to **☀️ Solar Simulation** or **💨 Wind Simulation** to run individual simulations
    2. Use **🔋 Battery Sizing** to add storage to your project
    3. Configure hybrid systems with **⚡ Dispatch Model**
    4. Analyze economics in **💰 LCoE Calculator**
    5. Find optimal configurations with **🎯 LCoE Optimizer**
    """)

with col2:
    st.markdown("""
    #### Key Features
    - **Modular Architecture**: Each component can be used independently
    - **Professional Grade**: Industry-standard loss models and calculations
    - **Morocco-Specific**: Built-in ANRE grid tariffs
    - **Optimization**: Find lowest LCoE configurations automatically
    """)

# Sidebar - Global project settings
st.sidebar.header("🌍 Project Settings")
st.sidebar.markdown("---")

# Store in session state for use across pages
if 'project_name' not in st.session_state:
    st.session_state.project_name = "Untitled Project"

st.session_state.project_name = st.sidebar.text_input(
    "Project Name",
    value=st.session_state.project_name
)

if 'latitude' not in st.session_state:
    st.session_state.latitude = 31.6
if 'longitude' not in st.session_state:
    st.session_state.longitude = -8.0

st.sidebar.subheader("📍 Site Location")
st.session_state.latitude = st.sidebar.number_input(
    "Latitude (°N)",
    value=st.session_state.latitude,
    min_value=-60.0,
    max_value=60.0,
    format="%.4f"
)
st.session_state.longitude = st.sidebar.number_input(
    "Longitude (°E)",
    value=st.session_state.longitude,
    min_value=-180.0,
    max_value=180.0,
    format="%.4f"
)

if 'project_life' not in st.session_state:
    st.session_state.project_life = 30
if 'wacc' not in st.session_state:
    st.session_state.wacc = 0.06

st.sidebar.subheader("💵 Financial Parameters")
st.session_state.project_life = st.sidebar.slider(
    "Project Life (Years)",
    min_value=20,
    max_value=35,
    value=st.session_state.project_life
)
st.session_state.wacc = st.sidebar.slider(
    "WACC (%)",
    min_value=4.0,
    max_value=12.0,
    value=st.session_state.wacc * 100,
    step=0.5
) / 100

st.sidebar.markdown("---")
st.sidebar.info("""
    📍 **Location**: {:.2f}°N, {:.2f}°E  
    📅 **Project Life**: {} years  
    💰 **WACC**: {:.1f}%
""".format(
    st.session_state.latitude,
    st.session_state.longitude,
    st.session_state.project_life,
    st.session_state.wacc * 100
))

# Footer
st.markdown("---")
st.markdown("""
<div style="text-align: center; color: #888; font-size: 0.9em;">
    Renewable Energy Simulator Pro v2.0 | Professional-grade simulation platform<br>
    Combines PVsyst + WindPro + Battery Sizing + Dispatch + LCoE Optimization
</div>
""", unsafe_allow_html=True)
