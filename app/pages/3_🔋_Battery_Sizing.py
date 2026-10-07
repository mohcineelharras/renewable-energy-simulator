"""
Battery Sizing Page

Battery energy storage system sizing and simulation.
"""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd

src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from simulator.storage.battery import BatteryStorage, BatteryConfig, BatteryChemistry
from simulator.data.timeseries import create_load_profile
from simulator.visualization.charts import create_soc_chart, create_dispatch_chart

st.set_page_config(page_title="Battery Sizing", page_icon="🔋", layout="wide")

st.title("🔋 Battery Energy Storage System")
st.markdown("**Sizing heuristic and an hourly state-of-charge balance.**")
st.caption("Chemistry fills efficiency and degradation only when those fields are left unset. Thermal loss percent is not applied.")

# Check for existing generation data
solar_result = st.session_state.get('solar_result')
wind_result = st.session_state.get('wind_result')

if solar_result is None and wind_result is None:
    st.warning("⚠️ No generation data available. Please run a Solar or Wind simulation first.")
    st.stop()

st.success("✅ Generation data available from previous simulations")

tab_config, tab_sizing, tab_simulation = st.tabs([
    "⚙️ Battery Configuration",
    "📐 Sizing",
    "🔄 Simulation"
])

with tab_config:
    col1, col2 = st.columns(2)
    
    with col1:
        st.subheader("Chemistry")
        chemistry = st.selectbox(
            "Battery Chemistry",
            [c.value for c in BatteryChemistry],
            format_func=lambda x: {
                'lfp': 'LFP (Lithium Iron Phosphate)',
                'nmc': 'NMC (Nickel Manganese Cobalt)',
                'nca': 'NCA (Nickel Cobalt Aluminum)',
                'lead_acid': 'Lead Acid'
            }.get(x, x)
        )
        
        st.subheader("Capacity")
        capacity_mwh = st.number_input("Energy Capacity (MWh)", value=100.0, min_value=1.0, step=10.0)
        power_mw = st.number_input("Power Capacity (MW)", value=25.0, min_value=1.0, step=5.0)
        st.info(f"**Duration**: {capacity_mwh/power_mw:.1f} hours | **C-rate**: {power_mw/capacity_mwh:.2f}C")
    
    with col2:
        st.subheader("Operating Limits")
        min_soc = st.slider("Minimum SoC (%)", 5, 20, 10) / 100
        max_soc = st.slider("Maximum SoC (%)", 80, 95, 90) / 100
        initial_soc = st.slider("Initial SoC (%)", 20, 80, 50) / 100
        
        st.subheader("Efficiency")
        rte = st.slider("Round-Trip Efficiency (%)", 75, 95, 90) / 100

with tab_sizing:
    st.subheader("Automatic Sizing")
    
    sizing_method = st.selectbox(
        "Sizing Method",
        ["self_consumption", "peak_shaving", "time_shifting", "arbitrage"],
        format_func=lambda x: {
            'self_consumption': '🏠 Self-Consumption (maximize on-site use)',
            'peak_shaving': '📉 Peak Shaving (reduce peak demand)',
            'time_shifting': '⏰ Time Shifting (store for later)',
            'arbitrage': '💹 Arbitrage (buy low, sell high)'
        }.get(x, x)
    )
    
    # Get generation profile
    if solar_result and wind_result:
        gen = solar_result.hourly['power_kw'] + wind_result.hourly['power_kw'].reindex(solar_result.hourly.index).fillna(0)
        st.info("Using combined Solar + Wind generation")
    elif solar_result:
        gen = solar_result.hourly['power_kw']
        st.info("Using Solar generation")
    else:
        gen = wind_result.hourly['power_kw']
        st.info("Using Wind generation")
    
    # Create load profile for sizing
    load_type = st.selectbox("Load Profile Type", ["commercial", "industrial", "residential"])
    peak_load = st.number_input("Peak Load (kW)", value=gen.max() * 0.8, min_value=0.0)
    
    load = create_load_profile(peak_load, load_type, index=gen.index)
    
    if st.button("📐 Calculate Size", type="primary"):
        with st.spinner("Calculating battery size..."):
            battery = BatteryStorage(BatteryConfig(
                chemistry=BatteryChemistry(chemistry)
            ))
            
            sizing_result = battery.size_for_application(
                gen, load, target=sizing_method
            )
            
            st.session_state['battery_sizing'] = sizing_result
        
        st.success("✅ Sizing Complete!")
        
        cols = st.columns(4)
        cols[0].metric("Recommended Capacity", f"{sizing_result.capacity_kwh/1000:.1f} MWh")
        cols[1].metric("Recommended Power", f"{sizing_result.power_kw/1000:.1f} MW")
        cols[2].metric("Duration", f"{sizing_result.duration_hours:.1f} hours")
        cols[3].metric("Method", sizing_method)
        
        st.info(f"**Rationale**: {sizing_result.rationale}")

with tab_simulation:
    st.subheader("Battery Simulation")
    
    dispatch_strategy = st.selectbox(
        "Dispatch Strategy",
        ["self_consumption", "peak_shaving"],
        format_func=lambda x: {
            'self_consumption': '🏠 Self-Consumption',
            'peak_shaving': '📉 Peak Shaving'
        }.get(x, x)
    )
    
    view_period = st.selectbox("View Period", ["week", "day", "month"], index=0)
    
    if st.button("🔄 Run Simulation", type="primary"):
        with st.spinner("Running battery simulation..."):
            config = BatteryConfig(
                capacity_kwh=capacity_mwh * 1000,
                power_kw=power_mw * 1000,
                chemistry=BatteryChemistry(chemistry),
                min_soc=min_soc,
                max_soc=max_soc,
                initial_soc=initial_soc,
                charge_efficiency=rte ** 0.5,
                discharge_efficiency=rte ** 0.5
            )
            
            battery = BatteryStorage(config)
            
            if solar_result and wind_result:
                gen = solar_result.hourly['power_kw'] + wind_result.hourly['power_kw'].reindex(solar_result.hourly.index).fillna(0)
            elif solar_result:
                gen = solar_result.hourly['power_kw']
            else:
                gen = wind_result.hourly['power_kw']
            
            load = create_load_profile(peak_load, load_type, index=gen.index)
            
            sim_result = battery.simulate(gen, load, dispatch_strategy)
            kpis = battery.get_kpis()
            
            st.session_state['battery_result'] = sim_result
            st.session_state['battery_kpis'] = kpis
        
        st.success("✅ Simulation Complete!")
        
        st.subheader("📊 Battery KPIs")
        cols = st.columns(5)
        cols[0].metric("Total Charged", f"{kpis['total_charged_kwh']/1000:,.0f} MWh")
        cols[1].metric("Total Discharged", f"{kpis['total_discharged_kwh']/1000:,.0f} MWh")
        cols[2].metric("Equivalent Cycles", f"{kpis['equivalent_cycles']:.0f}")
        cols[3].metric("Avg SoC", f"{kpis['avg_soc']*100:.1f}%")
        cols[4].metric("Utilization", f"{kpis['utilization_pct']:.1f}%")
        
        st.subheader("📈 Battery Operation")
        
        # Dispatch chart
        dispatch_df = pd.DataFrame({
            'total_generation_kw': gen.values,
            'load_kw': load.values,
            'storage_charge_kw': sim_result['charge_kw'].values,
            'storage_discharge_kw': sim_result['discharge_kw'].values,
        }, index=gen.index)
        
        fig = create_dispatch_chart(dispatch_df, "Generation & Battery Dispatch", view_period)
        st.plotly_chart(fig, use_container_width=True)
        
        # SoC chart
        fig = create_soc_chart(
            pd.Series(sim_result["soc"].values, index=gen.index),
            "State of Charge",
            view_period,
            min_soc=min_soc,
            max_soc=max_soc,
        )
        st.plotly_chart(fig, use_container_width=True)
