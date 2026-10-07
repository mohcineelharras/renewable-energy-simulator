"""
Solar PV Simulation Page

Solar screening model with auto-sizing and an energy-weighted loss waterfall.
"""
import streamlit as st
import sys
from pathlib import Path

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from simulator.generators.solar import SolarGenerator, SolarConfig
from simulator.financial.lcoe import LCOECalculator, FinancialConfig
from simulator.financial.tariffs import GridTariff, MoroccoGridTariffs
from simulator.financial.capex import SolarCapex
from simulator.financial.opex import SolarOpex
from simulator.data.weather import fetch_pvgis_tmy, generate_synthetic_solar_tmy
from simulator.visualization.charts import create_loss_waterfall, create_production_chart, create_capex_pie

st.set_page_config(page_title="Solar PV Simulation", page_icon="☀️", layout="wide")

st.title("☀️ Solar PV Simulation")
st.markdown("**Hourly screening model: isotropic POA, Faiman temperature, then flat loss fractions.**")
st.caption(
    "This is not a PVsyst model. IAM, inverter, and shading losses are the fractions you set, "
    "not incidence-angle or shade-scene calculations."
)

# Get global settings from session state
latitude = st.session_state.get('latitude', 31.6)
longitude = st.session_state.get('longitude', -8.0)
project_life = st.session_state.get('project_life', 30)
wacc = st.session_state.get('wacc', 0.06)

# Configuration tabs
tab_site, tab_system, tab_losses, tab_economics = st.tabs([
    "📍 Site Parameters",
    "🔧 System Design", 
    "⚙️ Loss Parameters",
    "💰 Economics"
])

with tab_site:
    col1, col2 = st.columns(2)
    with col1:
        land_area_ha = st.number_input("Land Area (hectares)", value=100.0, min_value=1.0, step=10.0)
        lat = st.number_input("Latitude (°N)", value=latitude, min_value=-60.0, max_value=60.0)
    with col2:
        grid_limit = st.number_input("Grid Limit (MW AC)", value=50.0, min_value=1.0, step=5.0)
        lon = st.number_input("Longitude (°E)", value=longitude, min_value=-180.0, max_value=180.0)

with tab_system:
    col1, col2 = st.columns(2)
    with col1:
        module_power = st.number_input("Module Power (Wp)", value=580, min_value=300, max_value=800, step=10)
        gcr = st.slider("Ground Coverage Ratio", 0.25, 0.45, 0.30, step=0.02,
                       help="Ratio of module area to land area. Lower = more spacing.")
    with col2:
        module_eff = st.slider("Module Efficiency (%)", 18.0, 24.0, 21.5) / 100
        ilr = st.slider("Inverter Loading Ratio (DC:AC)", 1.1, 1.5, 1.30, step=0.05)
    
    tracking = st.radio("Tracking System", ["fixed", "single_axis"], 
                        format_func=lambda x: "Fixed Tilt" if x == "fixed" else "Single-Axis Tracker")

with tab_losses:
    st.markdown("**Pre-DC Losses**")
    col1, col2, col3 = st.columns(3)
    with col1:
        loss_shading = st.slider("Near Shading (%)", 0.0, 5.0, 2.0) / 100
        loss_soiling = st.slider("Soiling (%)", 2.0, 15.0, 5.0) / 100
    with col2:
        loss_iam = st.slider("IAM Reflection (%)", 1.0, 5.0, 3.0) / 100
        loss_spectral = st.slider("Spectral (%)", 0.0, 2.0, 1.0) / 100
    with col3:
        loss_dc_wiring = st.slider("DC Wiring (%)", 1.0, 4.0, 2.0) / 100
        loss_mismatch = st.slider("Mismatch (%)", 0.5, 3.0, 1.5) / 100
    
    st.markdown("**AC Losses**")
    col1, col2, col3 = st.columns(3)
    with col1:
        loss_inverter = st.slider("Inverter Eff. (%)", 1.0, 4.0, 2.0) / 100
    with col2:
        loss_transformer = st.slider("Transformer (%)", 0.5, 3.0, 1.5) / 100
    with col3:
        loss_avail = st.slider("Availability (%)", 0.5, 3.0, 1.0) / 100
    
    degradation = st.slider("Annual Degradation (%)", 0.3, 1.0, 0.5) / 100

with tab_economics:
    st.markdown("**CAPEX ($/kWdc)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        capex_modules = st.number_input("Modules", value=115.0, step=5.0)
        capex_inverters = st.number_input("Inverters", value=40.0, step=5.0)
    with col2:
        capex_mounting = st.number_input("Mounting/Trackers", value=100.0, step=5.0)
        capex_bop = st.number_input("BOP/Electrical", value=160.0, step=10.0)
    with col3:
        capex_grid = st.number_input("Grid Connection", value=75.0, step=10.0)
        capex_dev = st.number_input("Development", value=40.0, step=5.0)
    
    st.markdown("**OPEX ($/kW/year)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        opex_maint = st.number_input("Scheduled Maint.", value=12.0, step=1.0)
    with col2:
        opex_repair = st.number_input("Unscheduled", value=4.0, step=0.5)
    with col3:
        opex_insur = st.number_input("Insurance", value=3.0, step=0.5)
    use_morocco_grid_charge = st.checkbox(
        "Subtract stored Morocco grid-charge assumption from revenue",
        value=False,
    )
    st.caption(
        "Stored constants: TURT 6.68 + TURD 5.92 + TSS 6.64 centimes/kWh, "
        "converted with mad_to_usd = 0.10. This is not a live tariff feed."
    )

# Run simulation button
st.markdown("---")
if st.button("🚀 Run Solar Simulation", type="primary", use_container_width=True):
    with st.spinner("Fetching weather data and running simulation..."):
        # Get weather data
        weather, weather_status = fetch_pvgis_tmy(lat, lon)
        if weather is None:
            weather = generate_synthetic_solar_tmy(lat, lon)
            weather_status = (
                f"{weather_status} Fell back to a synthetic solar series seeded from "
                "latitude and longitude. That series is not a climate dataset."
            )
        st.info(weather_status)
        
        # Configure
        config = SolarConfig(
            latitude=lat,
            longitude=lon,
            land_area_ha=land_area_ha,
            grid_limit_mw=grid_limit,
            module_power_wp=module_power,
            module_efficiency=module_eff,
            gcr=gcr,
            ilr=ilr,
            tracking=tracking,
            loss_near_shading=loss_shading,
            loss_soiling=loss_soiling,
            loss_iam=loss_iam,
            loss_spectral=loss_spectral,
            loss_dc_wiring=loss_dc_wiring,
            loss_mismatch=loss_mismatch,
            loss_inverter=loss_inverter,
            loss_transformer=loss_transformer,
            loss_availability=loss_avail,
            annual_degradation=degradation,
        )
        
        # Simulate
        generator = SolarGenerator(config)
        sizing = generator.auto_size()
        result = generator.simulate(weather, years=project_life)
        kpis = result.kpis
        
        # Financial calculation
        solar_capex = SolarCapex(
            modules=capex_modules,
            inverters=capex_inverters,
            mounting_trackers=capex_mounting,
            bop_electrical=capex_bop,
            grid_connection=capex_grid,
            development=capex_dev
        )
        solar_opex = SolarOpex(
            scheduled_maintenance=opex_maint,
            unscheduled_repairs=opex_repair,
            insurance=opex_insur
        )
        
        fin_calc = LCOECalculator(FinancialConfig(
            wacc=wacc,
            project_life_years=project_life,
            use_grid_tariffs=use_morocco_grid_charge,
            grid_tariff=MoroccoGridTariffs() if use_morocco_grid_charge else GridTariff(),
        ))
        fin_result = fin_calc.calculate_solar_lcoe(
            sizing.dc_capacity_kwp,
            result.annual['energy_mwh'].tolist(),
            solar_capex,
            solar_opex
        )
        
        # Calculate floor PPA
        floor_ppa = fin_calc.calculate_floor_ppa(
            solar_capex.total_for_capacity(sizing.dc_capacity_kwp),
            solar_opex.total_for_capacity(sizing.dc_capacity_kwp),
            result.annual['energy_mwh'].tolist()
        )
        
        # Store in session state
        st.session_state['solar_result'] = result
        st.session_state['solar_sizing'] = sizing
        st.session_state['solar_financial'] = fin_result
    
    # Display results
    st.success("✅ Simulation Complete!")
    
    # Sizing results
    st.subheader("📐 Auto-Sizing Results")
    cols = st.columns(5)
    cols[0].metric("DC Capacity", f"{sizing.dc_capacity_kwp/1000:.1f} MWp")
    cols[1].metric("AC Capacity", f"{sizing.ac_capacity_kw/1000:.1f} MW")
    cols[2].metric("Actual ILR", f"{sizing.actual_ilr:.2f}")
    cols[3].metric("Modules", f"{sizing.num_modules:,}")
    cols[4].metric("Land Use", f"{sizing.specific_area_m2_per_kwp:.1f} m²/kWp")
    
    # KPIs
    st.subheader("📊 Key Performance Indicators")
    cols = st.columns(4)
    cols[0].metric("Annual Energy (Year 1)", f"{kpis['annual_energy_mwh']:,.0f} MWh")
    cols[1].metric("Specific Yield", f"{kpis['specific_yield_kwh_kwp']:,.0f} kWh/kWp")
    cols[2].metric("Performance Ratio", f"{kpis['performance_ratio']:.2%}")
    cols[3].metric("Total Losses", f"{kpis['total_losses_pct']:.1f}%")
    
    # Financial KPIs
    st.subheader("💵 Financial Results")
    cols = st.columns(4)
    cols[0].metric("🎯 Floor PPA (NPV=0)", f"${floor_ppa:.2f}/MWh",
                   help="Minimum tariff needed to break even")
    cols[1].metric("LCoE", f"${fin_result.lcoe:.2f}/MWh")
    cols[2].metric("Total CAPEX", f"${fin_result.total_capex:,.0f}")
    cols[3].metric("CAPEX/Wp", f"${fin_result.total_capex/(sizing.dc_capacity_kwp*1000):.2f}")
    
    # Charts
    st.subheader("📈 Visualizations")
    col1, col2 = st.columns(2)
    
    with col1:
        losses = generator.get_losses()
        fig = create_loss_waterfall(losses, "Solar Loss Waterfall")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = create_production_chart(result.annual, f"{project_life}-Year Production Profile")
        st.plotly_chart(fig, use_container_width=True)
    
    # CAPEX breakdown
    fig = create_capex_pie(fin_result.breakdown.get('capex', {}), "CAPEX Breakdown")
    st.plotly_chart(fig, use_container_width=True)
