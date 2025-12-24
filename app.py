"""
Professional Renewable Energy Simulator
Utility-scale Solar and Wind with 30-year lifecycle and Morocco-specific financials.
"""
import streamlit as st
import pandas as pd
import numpy as np
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

from simulator.solar import PVSimulator, PVSystemConfig
from simulator.wind import WindSimulator, WindSystemConfig, TURBINE_LIBRARY
from simulator.finance import (
    FinancialModel, FinancialConfig, 
    SolarCapex, SolarOpex, WindCapex, WindOpex, MoroccoGridTariffs
)
from simulator.weather import fetch_pvgis_tmy, generate_synthetic_solar_tmy, generate_synthetic_wind_tmy

st.set_page_config(
    page_title="Renewable Energy Simulator Pro", 
    page_icon="⚡",
    layout="wide"
)

# Custom CSS
st.markdown("""
<style>
    .metric-card {
        background: linear-gradient(135deg, #1e3a5f 0%, #2d5a87 100%);
        border-radius: 12px;
        padding: 20px;
        color: white;
        text-align: center;
    }
    .stMetric { border: 1px solid #e0e0e0; border-radius: 8px; padding: 10px; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ Renewable Energy Simulator Pro")
st.markdown("**Utility-scale Solar & Wind · 30-Year Lifecycle · Morocco Financial Parameters**")

# ------------------------------------------------------------------
# HELPER FUNCTIONS
# ------------------------------------------------------------------
def create_loss_waterfall(loss_items: list, title: str) -> go.Figure:
    """Create a professional waterfall chart for losses."""
    labels = ["Gross Energy"] + [item.stage for item in loss_items] + ["Net Energy"]
    
    measures = ["absolute"]
    for item in loss_items:
        measures.append("relative")
    measures.append("total")
    
    values = [100]  # Start at 100%
    for item in loss_items:
        values.append(-item.loss_percent * 100)
    values.append(0)  # Total will be calculated
    
    texts = ["100%"]
    for item in loss_items:
        texts.append(f"-{item.loss_percent*100:.1f}%")
    # Calculate final
    final_pct = 100 + sum(values[1:-1])
    texts.append(f"{final_pct:.1f}%")
    
    fig = go.Figure(go.Waterfall(
        name="",
        orientation="v",
        measure=measures,
        x=labels,
        textposition="outside",
        text=texts,
        y=values,
        connector={"line": {"color": "rgba(63, 63, 63, 0.5)"}},
        decreasing={"marker": {"color": "#ff6b6b"}},
        increasing={"marker": {"color": "#51cf66"}},
        totals={"marker": {"color": "#339af0"}}
    ))
    
    fig.update_layout(
        title=title,
        showlegend=False,
        height=400,
        yaxis_title="Energy (%)",
        xaxis_tickangle=-45
    )
    
    return fig

def create_production_chart(annual_df: pd.DataFrame, title: str) -> go.Figure:
    """Create 30-year production chart with degradation."""
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    fig.add_trace(
        go.Bar(
            x=annual_df['Year'],
            y=annual_df['Annual Energy (MWh)'],
            name="Annual Energy",
            marker_color='#339af0'
        ),
        secondary_y=False
    )
    
    fig.add_trace(
        go.Scatter(
            x=annual_df['Year'],
            y=annual_df['Cumulative Energy (MWh)'],
            name="Cumulative",
            line=dict(color='#ff6b6b', width=2)
        ),
        secondary_y=True
    )
    
    fig.update_layout(
        title=title,
        height=400,
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    fig.update_yaxes(title_text="Annual (MWh)", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative (MWh)", secondary_y=True)
    
    return fig

def create_capex_pie(breakdown: dict, title: str) -> go.Figure:
    """Create CAPEX breakdown pie chart."""
    fig = go.Figure(data=[go.Pie(
        labels=list(breakdown.keys()),
        values=list(breakdown.values()),
        hole=0.4,
        textinfo='label+percent',
        marker_colors=px.colors.qualitative.Set3
    )])
    fig.update_layout(title=title, height=350)
    return fig

# ------------------------------------------------------------------
# SIDEBAR - Global Parameters
# ------------------------------------------------------------------
st.sidebar.header("🌍 Project Parameters")

project_life = st.sidebar.slider("Project Life (Years)", 20, 35, 30)
wacc = st.sidebar.slider("WACC (%)", 4.0, 12.0, 6.0) / 100

st.sidebar.header("🇲🇦 Morocco Grid Tariffs")
use_morocco = st.sidebar.checkbox("Apply Morocco Grid Tariffs", value=True)
if use_morocco:
    st.sidebar.caption("ANRE 2025: TURT 6.68 + TURD 5.92 + TSS 6.64 = **19.24 c/kWh** (~$19/MWh)")

# ------------------------------------------------------------------
# MAIN TABS
# ------------------------------------------------------------------
tab1, tab2 = st.tabs(["☀️ Solar PV Park", "💨 Wind Farm"])

# ==================================================================
# SOLAR TAB
# ==================================================================
with tab1:
    st.header("☀️ Utility-Scale Solar PV Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📍 Site Parameters")
        land_area_ha = st.number_input("Land Area (hectares)", value=100.0, min_value=1.0, step=10.0, key="pv_land")
        latitude = st.number_input("Latitude (°N)", value=31.6, min_value=-60.0, max_value=60.0, key="pv_lat")
        longitude = st.number_input("Longitude (°E)", value=-8.0, min_value=-180.0, max_value=180.0, key="pv_lon")
        grid_limit = st.number_input("Grid Limit (MW AC)", value=50.0, min_value=1.0, step=5.0, key="pv_grid")
    
    with col2:
        st.subheader("🔧 System Design")
        module_power = st.number_input("Module Power (Wp)", value=580, min_value=300, max_value=800, step=10, key="pv_mod")
        module_eff = st.slider("Module Efficiency (%)", 18.0, 24.0, 21.5, key="pv_eff") / 100
        gcr = st.slider("Ground Coverage Ratio", 0.25, 0.45, 0.30, step=0.02, key="pv_gcr",
                       help="Ratio of module area to land area. Lower = more spacing. Typical: 0.25-0.35 for trackers")
        ilr = st.slider("Inverter Loading Ratio (DC:AC)", 1.1, 1.5, 1.30, step=0.05, key="pv_ilr")
    
    # Loss Parameters
    with st.expander("⚙️ Loss Parameters (Advanced)"):
        loss_cols = st.columns(4)
        with loss_cols[0]:
            loss_shading = st.slider("Near Shading (%)", 0.0, 5.0, 2.0, key="pv_l1") / 100
            loss_soiling = st.slider("Soiling (%)", 2.0, 15.0, 5.0, key="pv_l2") / 100
            loss_iam = st.slider("IAM Reflection (%)", 1.0, 5.0, 3.0, key="pv_l3") / 100
        with loss_cols[1]:
            loss_spectral = st.slider("Spectral (%)", 0.0, 2.0, 1.0, key="pv_l4") / 100
            loss_dc_wiring = st.slider("DC Wiring (%)", 1.0, 4.0, 2.0, key="pv_l5") / 100
            loss_mismatch = st.slider("Mismatch (%)", 0.5, 3.0, 1.5, key="pv_l6") / 100
        with loss_cols[2]:
            loss_inverter = st.slider("Inverter Eff. (%)", 1.0, 4.0, 2.0, key="pv_l7") / 100
            loss_transformer = st.slider("Transformer (%)", 0.5, 3.0, 1.5, key="pv_l8") / 100
            loss_ac = st.slider("AC Collection (%)", 0.5, 2.0, 1.0, key="pv_l9") / 100
        with loss_cols[3]:
            loss_avail = st.slider("Availability (%)", 0.5, 3.0, 1.0, key="pv_l10") / 100
            degradation = st.slider("Annual Degradation (%)", 0.3, 1.0, 0.5, key="pv_deg") / 100
    
    # Economic Parameters
    with st.expander("💰 Economic Parameters (CAPEX / OPEX)"):
        st.markdown("**CAPEX ($/kWdc)**")
        capex_cols = st.columns(4)
        with capex_cols[0]:
            capex_modules = st.number_input("Modules", value=115.0, step=5.0, key="pv_cap1")
            capex_inverters = st.number_input("Inverters", value=40.0, step=5.0, key="pv_cap2")
        with capex_cols[1]:
            capex_mounting = st.number_input("Mounting/Trackers", value=100.0, step=5.0, key="pv_cap3")
            capex_bop = st.number_input("BOP/Electrical", value=160.0, step=10.0, key="pv_cap4")
        with capex_cols[2]:
            capex_epc_pct = st.number_input("EPC (%)", value=12.0, step=1.0, key="pv_cap5") / 100
            capex_grid = st.number_input("Grid Connection", value=75.0, step=10.0, key="pv_cap6")
        with capex_cols[3]:
            capex_dev = st.number_input("Development", value=40.0, step=5.0, key="pv_cap7")
        
        st.markdown("**OPEX ($/kW/year)**")
        opex_cols = st.columns(5)
        with opex_cols[0]:
            opex_maint = st.number_input("Scheduled Maint.", value=12.0, step=1.0, key="pv_op1")
        with opex_cols[1]:
            opex_repair = st.number_input("Unscheduled", value=4.0, step=0.5, key="pv_op2")
        with opex_cols[2]:
            opex_insur = st.number_input("Insurance", value=3.0, step=0.5, key="pv_op3")
        with opex_cols[3]:
            opex_land = st.number_input("Land Lease", value=2.0, step=0.5, key="pv_op4")
        with opex_cols[4]:
            opex_admin = st.number_input("Administrative", value=1.5, step=0.5, key="pv_op5")
    
    if st.button("🚀 Run Solar Simulation", type="primary", key="run_pv"):
        with st.spinner("Fetching PVGIS data and running 30-year simulation..."):
            # Fetch TMY data from PVGIS
            weather, pvgis_status = fetch_pvgis_tmy(latitude, longitude)
            if weather is None:
                weather = generate_synthetic_solar_tmy(latitude)
            
            st.info(pvgis_status)
            
            # Configure
            config = PVSystemConfig(
                land_area_ha=land_area_ha,
                latitude=latitude,
                longitude=longitude,
                grid_limit_mw=grid_limit,
                module_power_wp=module_power,
                module_efficiency=module_eff,
                gcr=gcr,
                ilr=ilr,
                loss_near_shading=loss_shading,
                loss_soiling=loss_soiling,
                loss_iam=loss_iam,
                loss_spectral=loss_spectral,
                loss_dc_wiring=loss_dc_wiring,
                loss_mismatch=loss_mismatch,
                loss_inverter_efficiency=loss_inverter,
                loss_transformer=loss_transformer,
                loss_ac_collection=loss_ac,
                loss_availability=loss_avail,
                annual_degradation=degradation
            )
            
            # Simulate
            sim = PVSimulator(config)
            sizing = sim.auto_size()
            sim.simulate_year_one(weather)
            annual_results = sim.run_lifecycle(weather, project_life)
            kpis = sim.get_kpis()
            
            # Create CAPEX/OPEX objects with user values
            solar_capex = SolarCapex(
                modules=capex_modules,
                inverters=capex_inverters,
                mounting_trackers=capex_mounting,
                bop_electrical=capex_bop,
                epc_percent=capex_epc_pct,
                grid_connection=capex_grid,
                development=capex_dev
            )
            solar_opex = SolarOpex(
                scheduled_maintenance=opex_maint,
                unscheduled_repairs=opex_repair,
                insurance=opex_insur,
                land_lease=opex_land,
                administrative=opex_admin
            )
            
            # Financial
            fin_config = FinancialConfig(
                wacc=wacc,
                project_life_years=project_life,
                ppa_tariff_usd_per_mwh=0,  # Not used for floor calculation
                use_morocco_grid_tariffs=use_morocco
            )
            fin = FinancialModel(fin_config)
            
            # Calculate floor PPA (minimum tariff for NPV=0)
            total_capex = solar_capex.total_per_kwdc() * sizing.dc_capacity_kwp
            annual_opex_base = solar_opex.total_per_kw_year() * sizing.dc_capacity_kwp
            floor_ppa = fin.calculate_floor_ppa(
                total_capex,
                annual_opex_base,
                annual_results['Annual Energy (MWh)'].tolist()
            )
            
            # Now calculate full financials with floor PPA
            fin_config.ppa_tariff_usd_per_mwh = floor_ppa
            fin_results = fin.calculate_solar_lcoe(
                sizing.dc_capacity_kwp,
                annual_results['Annual Energy (MWh)'].tolist(),
                solar_capex,
                solar_opex
            )
        
        # Results
        st.success("✅ Simulation Complete!")
        
        # Auto-Sizing Results
        st.subheader("📐 Auto-Sizing Results")
        size_cols = st.columns(5)
        size_cols[0].metric("DC Capacity", f"{sizing.dc_capacity_kwp/1000:.1f} MWp")
        size_cols[1].metric("AC Capacity", f"{sizing.ac_capacity_kw/1000:.1f} MW")
        size_cols[2].metric("Actual ILR", f"{sizing.actual_ilr:.2f}")
        size_cols[3].metric("Modules", f"{sizing.num_modules:,}")
        size_cols[4].metric("Land Use", f"{sizing.specific_area_m2_per_kwp:.1f} m²/kWp")
        
        # KPIs
        st.subheader("📊 Key Performance Indicators")
        kpi_cols = st.columns(4)
        kpi_cols[0].metric("Annual Energy (Year 1)", f"{kpis['Annual Energy (MWh)']:,.0f} MWh")
        kpi_cols[1].metric("Specific Yield", f"{kpis['Specific Yield (kWh/kWp)']:,.0f} kWh/kWp")
        kpi_cols[2].metric("Performance Ratio", f"{kpis['Performance Ratio']:.2%}")
        kpi_cols[3].metric("Total Losses", f"{kpis['Total Losses (%)']:.1f}%")
        
        # Financial KPIs - Floor PPA is the OUTPUT
        st.subheader("💵 Financial Results")
        fin_cols = st.columns(4)
        fin_cols[0].metric("🎯 Floor PPA (NPV=0)", f"${floor_ppa:.2f}/MWh", 
                          help="Minimum tariff needed to break even")
        fin_cols[1].metric("LCoE", f"${fin_results['LCOE ($/MWh)']:.2f}/MWh")
        fin_cols[2].metric("Total CAPEX", f"${fin_results['Total CAPEX ($)']:,.0f}")
        fin_cols[3].metric("CAPEX/Wp", f"${fin_results['Total CAPEX ($)']/(sizing.dc_capacity_kwp*1000):.2f}")
        
        # Charts
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.plotly_chart(
                create_loss_waterfall(sim.loss_waterfall, "Solar Loss Waterfall"),
                use_container_width=True
            )
        with chart_cols[1]:
            st.plotly_chart(
                create_production_chart(annual_results, "30-Year Production Profile"),
                use_container_width=True
            )
        
        # CAPEX Chart
        st.plotly_chart(
            create_capex_pie(fin_results['CAPEX Breakdown'], "CAPEX Breakdown"),
            use_container_width=True
        )

# ==================================================================
# WIND TAB
# ==================================================================
with tab2:
    st.header("💨 Utility-Scale Wind Farm Configuration")
    
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("📍 Site Parameters")
        wind_land = st.number_input("Land Area (hectares)", value=500.0, min_value=10.0, step=50.0, key="wind_land")
        wind_lat = st.number_input("Latitude (°N)", value=35.0, min_value=-60.0, max_value=60.0, key="wind_lat")
        wind_lon = st.number_input("Longitude (°E)", value=-5.0, min_value=-180.0, max_value=180.0, key="wind_lon")
        wind_grid = st.number_input("Grid Limit (MW)", value=50.0, min_value=1.0, step=5.0, key="wind_grid")
    
    with col2:
        st.subheader("🔧 Turbine Selection")
        turbine_model = st.selectbox("Turbine Model", list(TURBINE_LIBRARY.keys()), key="wind_turb")
        selected_turbine = TURBINE_LIBRARY[turbine_model]
        st.info(f"**{selected_turbine.name}**: {selected_turbine.rated_power_kw/1000:.1f} MW · {selected_turbine.rotor_diameter_m}m RD · {selected_turbine.hub_height_m}m Hub")
        
        spacing_row = st.slider("Spacing In-Row (× RD)", 3.0, 5.0, 4.0, step=0.5, key="wind_sp1")
        spacing_col = st.slider("Spacing Between Rows (× RD)", 5.0, 9.0, 7.0, step=0.5, key="wind_sp2")
    
    # Loss Parameters
    with st.expander("⚙️ Loss Parameters (Advanced)"):
        wind_loss_cols = st.columns(3)
        with wind_loss_cols[0]:
            wloss_wake = st.slider("Wake Effects (%)", 5.0, 15.0, 10.0, key="wl1") / 100
            wloss_avail = st.slider("Availability (%)", 1.0, 5.0, 3.0, key="wl2") / 100
        with wind_loss_cols[1]:
            wloss_elec = st.slider("Electrical (%)", 1.0, 4.0, 2.0, key="wl3") / 100
            wloss_perf = st.slider("Performance (%)", 0.5, 3.0, 1.5, key="wl4") / 100
        with wind_loss_cols[2]:
            wloss_env = st.slider("Environmental (%)", 1.0, 5.0, 2.0, key="wl5") / 100
            wloss_grid = st.slider("Grid (%)", 0.5, 3.0, 1.0, key="wl6") / 100
            wind_deg = st.slider("Annual Degradation (%)", 0.5, 1.5, 0.8, key="wind_deg") / 100
    
    # Economic Parameters
    with st.expander("💰 Economic Parameters (CAPEX / OPEX)"):
        st.markdown("**CAPEX ($/kW)**")
        wcapex_cols = st.columns(3)
        with wcapex_cols[0]:
            wcapex_turbine = st.number_input("Turbine & Tower", value=1048.0, step=50.0, key="w_cap1")
            wcapex_found = st.number_input("Foundations", value=96.0, step=10.0, key="w_cap2")
        with wcapex_cols[1]:
            wcapex_install = st.number_input("Installation", value=124.0, step=10.0, key="w_cap3")
            wcapex_grid = st.number_input("Grid Connection", value=94.0, step=10.0, key="w_cap4")
        with wcapex_cols[2]:
            wcapex_dev = st.number_input("Development/BOS", value=157.0, step=10.0, key="w_cap5")
            wcapex_cont = st.number_input("Contingency", value=118.0, step=10.0, key="w_cap6")
        
        st.markdown("**OPEX ($/kW/year)**")
        wopex_cols = st.columns(5)
        with wopex_cols[0]:
            wopex_maint = st.number_input("Scheduled Maint.", value=32.0, step=2.0, key="w_op1")
        with wopex_cols[1]:
            wopex_repair = st.number_input("Unscheduled", value=12.0, step=1.0, key="w_op2")
        with wopex_cols[2]:
            wopex_insur = st.number_input("Insurance", value=4.0, step=0.5, key="w_op3")
        with wopex_cols[3]:
            wopex_land = st.number_input("Land Lease", value=3.0, step=0.5, key="w_op4")
        with wopex_cols[4]:
            wopex_admin = st.number_input("Administrative", value=3.0, step=0.5, key="w_op5")
    
    if st.button("🚀 Run Wind Simulation", type="primary", key="run_wind"):
        with st.spinner("Running 30-year wind simulation..."):
            # Generate wind weather data
            weather = generate_synthetic_wind_tmy(wind_lat)
            
            # Configure
            config = WindSystemConfig(
                land_area_ha=wind_land,
                latitude=wind_lat,
                longitude=wind_lon,
                grid_limit_mw=wind_grid,
                turbine_spec=selected_turbine,
                spacing_in_row_rd=spacing_row,
                spacing_between_rows_rd=spacing_col,
                loss_wake=wloss_wake,
                loss_availability=wloss_avail,
                loss_electrical=wloss_elec,
                loss_performance=wloss_perf,
                loss_environmental=wloss_env,
                loss_grid=wloss_grid,
                annual_degradation=wind_deg
            )
            
            # Simulate
            sim = WindSimulator(config)
            sizing = sim.auto_size()
            sim.simulate_year_one(weather)
            annual_results = sim.run_lifecycle(weather, project_life)
            kpis = sim.get_kpis()
            
            # Create CAPEX/OPEX objects with user values
            wind_capex = WindCapex(
                turbine_tower=wcapex_turbine,
                foundations=wcapex_found,
                installation=wcapex_install,
                grid_connection=wcapex_grid,
                development_bos=wcapex_dev,
                contingency=wcapex_cont
            )
            wind_opex = WindOpex(
                scheduled_maintenance=wopex_maint,
                unscheduled_repairs=wopex_repair,
                insurance=wopex_insur,
                land_lease=wopex_land,
                administrative=wopex_admin
            )
            
            # Financial
            fin_config = FinancialConfig(
                wacc=wacc,
                project_life_years=project_life,
                ppa_tariff_usd_per_mwh=0,
                use_morocco_grid_tariffs=use_morocco
            )
            fin = FinancialModel(fin_config)
            
            # Calculate floor PPA
            total_capex = wind_capex.total_per_kw() * sizing.total_capacity_mw * 1000
            annual_opex_base = wind_opex.total_per_kw_year() * sizing.total_capacity_mw * 1000
            floor_ppa = fin.calculate_floor_ppa(
                total_capex,
                annual_opex_base,
                annual_results['Annual Energy (MWh)'].tolist()
            )
            
            fin_config.ppa_tariff_usd_per_mwh = floor_ppa
            fin_results = fin.calculate_wind_lcoe(
                sizing.total_capacity_mw * 1000,
                annual_results['Annual Energy (MWh)'].tolist(),
                wind_capex,
                wind_opex
            )
        
        # Results
        st.success("✅ Simulation Complete!")
        
        # Auto-Sizing Results
        st.subheader("📐 Auto-Sizing Results")
        size_cols = st.columns(5)
        size_cols[0].metric("Total Capacity", f"{sizing.total_capacity_mw:.1f} MW")
        size_cols[1].metric("Turbines", f"{sizing.num_turbines}")
        size_cols[2].metric("Grid Constrained", "Yes" if sizing.grid_constrained else "No")
        size_cols[3].metric("Row Spacing", f"{sizing.spacing_in_row_m:.0f} m")
        size_cols[4].metric("Col Spacing", f"{sizing.spacing_between_rows_m:.0f} m")
        
        # KPIs
        st.subheader("📊 Key Performance Indicators")
        kpi_cols = st.columns(4)
        kpi_cols[0].metric("AEP (Year 1)", f"{kpis['Annual Energy (MWh)']:,.0f} MWh")
        kpi_cols[1].metric("Capacity Factor", f"{kpis['Capacity Factor (%)']:.1f}%")
        kpi_cols[2].metric("Full Load Hours", f"{kpis['Full Load Hours']:,.0f} h")
        kpi_cols[3].metric("Total Losses", f"{kpis['Total Losses (%)']:.1f}%")
        
        # Financial KPIs
        st.subheader("💵 Financial Results")
        fin_cols = st.columns(4)
        fin_cols[0].metric("🎯 Floor PPA (NPV=0)", f"${floor_ppa:.2f}/MWh",
                          help="Minimum tariff needed to break even")
        fin_cols[1].metric("LCoE", f"${fin_results['LCOE ($/MWh)']:.2f}/MWh")
        fin_cols[2].metric("Total CAPEX", f"${fin_results['Total CAPEX ($)']:,.0f}")
        fin_cols[3].metric("CAPEX/kW", f"${fin_results['Total CAPEX ($)']/(sizing.total_capacity_mw*1000):.0f}")
        
        # Charts
        chart_cols = st.columns(2)
        with chart_cols[0]:
            st.plotly_chart(
                create_loss_waterfall(sim.loss_waterfall, "Wind Loss Waterfall"),
                use_container_width=True
            )
        with chart_cols[1]:
            st.plotly_chart(
                create_production_chart(annual_results, "30-Year Production Profile"),
                use_container_width=True
            )
        
        # CAPEX Chart
        st.plotly_chart(
            create_capex_pie(fin_results['CAPEX Breakdown'], "CAPEX Breakdown"),
            use_container_width=True
        )
