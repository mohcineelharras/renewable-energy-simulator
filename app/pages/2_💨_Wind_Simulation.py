"""
Wind Farm Simulation Page

Wind screening model with a nameplate library and an idealized power curve.
"""
import streamlit as st
import sys
from pathlib import Path

src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from simulator.generators.wind import WindGenerator, WindConfig, TURBINE_LIBRARY
from simulator.financial.lcoe import LCOECalculator, FinancialConfig
from simulator.financial.tariffs import GridTariff, MoroccoGridTariffs
from simulator.financial.capex import WindCapex
from simulator.financial.opex import WindOpex
from simulator.data.weather import generate_synthetic_wind_tmy
from simulator.visualization.charts import create_loss_waterfall, create_production_chart, create_capex_pie

st.set_page_config(page_title="Wind Simulation", page_icon="💨", layout="wide")

st.title("💨 Wind Farm Simulation")
st.markdown("**Idealized cubic power curve, logarithmic shear, then flat loss fractions.**")
st.caption(
    "This is not a WindPro model. Named turbines share one curve scaled by nameplate. "
    "Wake is the fraction you set, not a spatial wake calculation."
)

latitude = st.session_state.get('latitude', 35.0)
longitude = st.session_state.get('longitude', -5.0)
project_life = st.session_state.get('project_life', 30)
wacc = st.session_state.get('wacc', 0.06)

tab_site, tab_turbine, tab_losses, tab_economics = st.tabs([
    "📍 Site Parameters",
    "🔧 Turbine Selection",
    "⚙️ Loss Parameters", 
    "💰 Economics"
])

with tab_site:
    col1, col2 = st.columns(2)
    with col1:
        land_area = st.number_input("Land Area (hectares)", value=500.0, min_value=10.0, step=50.0)
        lat = st.number_input("Latitude (°N)", value=latitude, min_value=-60.0, max_value=60.0)
    with col2:
        grid_limit = st.number_input("Grid Limit (MW)", value=50.0, min_value=1.0, step=5.0)
        lon = st.number_input("Longitude (°E)", value=longitude, min_value=-180.0, max_value=180.0)

with tab_turbine:
    turbine_model = st.selectbox("Turbine Model", list(TURBINE_LIBRARY.keys()))
    turbine = TURBINE_LIBRARY[turbine_model]
    st.info(f"**{turbine.name}**: {turbine.rated_power_kw/1000:.1f} MW nameplate · "
            f"{turbine.rotor_diameter_m}m rotor · {turbine.hub_height_m}m hub. "
            f"Cut-in {turbine.cut_in_speed:.0f} / rated {turbine.rated_speed:.0f} / "
            f"cut-out {turbine.cut_out_speed:.0f} m/s on the shared idealized curve.")
    
    col1, col2 = st.columns(2)
    with col1:
        spacing_row = st.slider("Spacing In-Row (× RD)", 3.0, 5.0, 4.0, step=0.5)
    with col2:
        spacing_col = st.slider("Spacing Between Rows (× RD)", 5.0, 9.0, 7.0, step=0.5)

with tab_losses:
    col1, col2 = st.columns(2)
    with col1:
        loss_wake = st.slider("Wake Effects (%)", 5.0, 15.0, 10.0) / 100
        loss_avail = st.slider("Availability (%)", 1.0, 5.0, 3.0) / 100
        loss_elec = st.slider("Electrical (%)", 1.0, 4.0, 2.0) / 100
    with col2:
        loss_perf = st.slider("Performance (%)", 0.5, 3.0, 1.5) / 100
        loss_env = st.slider("Environmental (%)", 1.0, 5.0, 2.0) / 100
        loss_grid = st.slider("Grid (%)", 0.5, 3.0, 1.0) / 100
    
    degradation = st.slider("Annual Degradation (%)", 0.5, 1.5, 0.8) / 100

with tab_economics:
    st.markdown("**CAPEX ($/kW)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        capex_turbine = st.number_input("Turbine & Tower", value=1048.0, step=50.0)
        capex_found = st.number_input("Foundations", value=96.0, step=10.0)
    with col2:
        capex_install = st.number_input("Installation", value=124.0, step=10.0)
        capex_grid = st.number_input("Grid Connection", value=94.0, step=10.0)
    with col3:
        capex_dev = st.number_input("Development/BOS", value=157.0, step=10.0)
        capex_cont = st.number_input("Contingency", value=118.0, step=10.0)
    
    st.markdown("**OPEX ($/kW/year)**")
    col1, col2, col3 = st.columns(3)
    with col1:
        opex_maint = st.number_input("Scheduled Maint.", value=32.0, step=2.0, key="w_opex1")
    with col2:
        opex_repair = st.number_input("Unscheduled", value=12.0, step=1.0, key="w_opex2")
    with col3:
        opex_insur = st.number_input("Insurance", value=4.0, step=0.5, key="w_opex3")
    use_morocco_grid_charge = st.checkbox(
        "Subtract stored Morocco grid-charge assumption from revenue",
        value=False,
        key="wind_morocco_grid_charge",
    )
    st.caption(
        "Stored constants: TURT 6.68 + TURD 5.92 + TSS 6.64 centimes/kWh, "
        "converted with mad_to_usd = 0.10. This is not a live tariff feed."
    )

st.markdown("---")
if st.button("🚀 Run Wind Simulation", type="primary", use_container_width=True):
    with st.spinner("Running wind simulation..."):
        weather = generate_synthetic_wind_tmy(lat, lon)
        
        config = WindConfig(
            latitude=lat,
            longitude=lon,
            land_area_ha=land_area,
            grid_limit_mw=grid_limit,
            turbine_model=turbine_model,
            spacing_in_row_rd=spacing_row,
            spacing_between_rows_rd=spacing_col,
            loss_wake=loss_wake,
            loss_availability=loss_avail,
            loss_electrical=loss_elec,
            loss_performance=loss_perf,
            loss_environmental=loss_env,
            loss_grid=loss_grid,
            annual_degradation=degradation,
        )
        
        generator = WindGenerator(config)
        sizing = generator.auto_size()
        result = generator.simulate(weather, years=project_life)
        kpis = result.kpis
        
        wind_capex = WindCapex(
            turbine_tower=capex_turbine,
            foundations=capex_found,
            installation=capex_install,
            grid_connection=capex_grid,
            development_bos=capex_dev,
            contingency=capex_cont
        )
        wind_opex = WindOpex(
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
        fin_result = fin_calc.calculate_wind_lcoe(
            sizing.total_capacity_mw * 1000,
            result.annual['energy_mwh'].tolist(),
            wind_capex,
            wind_opex
        )
        
        floor_ppa = fin_calc.calculate_floor_ppa(
            wind_capex.total_for_capacity(sizing.total_capacity_mw * 1000),
            wind_opex.total_for_capacity(sizing.total_capacity_mw * 1000),
            result.annual['energy_mwh'].tolist()
        )
        
        st.session_state['wind_result'] = result
        st.session_state['wind_sizing'] = sizing
        st.session_state['wind_financial'] = fin_result
    
    st.success("✅ Simulation Complete!")
    
    st.subheader("📐 Auto-Sizing Results")
    cols = st.columns(5)
    cols[0].metric("Total Capacity", f"{sizing.total_capacity_mw:.1f} MW")
    cols[1].metric("Turbines", f"{sizing.num_turbines}")
    cols[2].metric("Grid Constrained", "Yes" if sizing.grid_constrained else "No")
    cols[3].metric("Row Spacing", f"{sizing.spacing_in_row_m:.0f} m")
    cols[4].metric("Col Spacing", f"{sizing.spacing_between_rows_m:.0f} m")
    
    st.subheader("📊 Key Performance Indicators")
    cols = st.columns(4)
    cols[0].metric("AEP (Year 1)", f"{kpis['annual_energy_mwh']:,.0f} MWh")
    cols[1].metric("Capacity Factor", f"{kpis['capacity_factor_pct']:.1f}%")
    cols[2].metric("Full Load Hours", f"{kpis['full_load_hours']:,.0f} h")
    cols[3].metric("Total Losses", f"{kpis['total_losses_pct']:.1f}%")
    
    st.subheader("💵 Financial Results")
    cols = st.columns(4)
    cols[0].metric("🎯 Floor PPA (NPV=0)", f"${floor_ppa:.2f}/MWh")
    cols[1].metric("LCoE", f"${fin_result.lcoe:.2f}/MWh")
    cols[2].metric("Total CAPEX", f"${fin_result.total_capex:,.0f}")
    cols[3].metric("CAPEX/kW", f"${fin_result.total_capex/(sizing.total_capacity_mw*1000):.0f}")
    
    st.subheader("📈 Visualizations")
    col1, col2 = st.columns(2)
    
    with col1:
        fig = create_loss_waterfall(generator.get_losses(), "Wind Loss Waterfall")
        st.plotly_chart(fig, use_container_width=True)
    
    with col2:
        fig = create_production_chart(result.annual, f"{project_life}-Year Production Profile")
        st.plotly_chart(fig, use_container_width=True)
    
    fig = create_capex_pie(fin_result.breakdown.get('capex', {}), "CAPEX Breakdown")
    st.plotly_chart(fig, use_container_width=True)
