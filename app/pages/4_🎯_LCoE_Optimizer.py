"""
LCoE Optimizer Page

Find optimal system configuration to minimize LCoE.
"""
import streamlit as st
import sys
from pathlib import Path
import pandas as pd
import time

src_path = Path(__file__).parent.parent.parent / "src"
if str(src_path) not in sys.path:
    sys.path.insert(0, str(src_path))

from simulator.api import SimulationAPI
from simulator.optimizer.lcoe_optimizer import LCOEOptimizer, OptimizationConfig, OptimizationAlgorithm
from simulator.visualization.optimization import (
    create_pareto_chart, 
    create_convergence_chart, 
    create_sensitivity_tornado
)

st.set_page_config(page_title="LCoE Optimizer", page_icon="🎯", layout="wide")

st.title("🎯 LCoE Optimizer")
st.markdown("**Find the optimal system configuration to minimize Levelized Cost of Energy**")

latitude = st.session_state.get('latitude', 31.6)
longitude = st.session_state.get('longitude', -8.0)
project_life = st.session_state.get('project_life', 30)
wacc = st.session_state.get('wacc', 0.06)

tab_config, tab_run, tab_results = st.tabs([
    "⚙️ Optimization Variables",
    "🚀 Run Optimization",
    "📊 Results"
])

with tab_config:
    st.subheader("Define Search Space")
    st.markdown("Set the range for each variable to optimize:")
    
    col1, col2, col3 = st.columns(3)
    
    with col1:
        st.markdown("**☀️ Solar PV**")
        solar_min = st.number_input("Min Solar (MW)", value=0.0, min_value=0.0, step=10.0)
        solar_max = st.number_input("Max Solar (MW)", value=100.0, min_value=0.0, step=10.0)
        solar_step = st.number_input("Step (MW)", value=20.0, min_value=5.0, step=5.0, key="solar_step")
    
    with col2:
        st.markdown("**💨 Wind**")
        wind_min = st.number_input("Min Wind (MW)", value=0.0, min_value=0.0, step=10.0)
        wind_max = st.number_input("Max Wind (MW)", value=50.0, min_value=0.0, step=10.0)
        wind_step = st.number_input("Step (MW)", value=10.0, min_value=5.0, step=5.0, key="wind_step")
    
    with col3:
        st.markdown("**🔋 Battery**")
        batt_min = st.number_input("Min Battery (MWh)", value=0.0, min_value=0.0, step=50.0)
        batt_max = st.number_input("Max Battery (MWh)", value=200.0, min_value=0.0, step=50.0)
        batt_step = st.number_input("Step (MWh)", value=50.0, min_value=10.0, step=10.0, key="batt_step")
    
    # Calculate total combinations
    solar_points = int((solar_max - solar_min) / solar_step) + 1 if solar_step > 0 else 1
    wind_points = int((wind_max - wind_min) / wind_step) + 1 if wind_step > 0 else 1
    batt_points = int((batt_max - batt_min) / batt_step) + 1 if batt_step > 0 else 1
    total_combos = solar_points * wind_points * batt_points
    
    st.info(f"**Total configurations to evaluate**: {total_combos:,} (Grid Search)")

with tab_run:
    st.subheader("Optimization Settings")
    
    col1, col2 = st.columns(2)
    
    with col1:
        algorithm = st.selectbox(
            "Algorithm",
            ["grid_search", "random_search", "genetic"],
            format_func=lambda x: {
                'grid_search': '🔲 Grid Search (exhaustive)',
                'random_search': '🎲 Random Search (fast)',
                'genetic': '🧬 Genetic Algorithm (smart)'
            }.get(x, x)
        )
        
        if algorithm != "grid_search":
            n_iterations = st.number_input("Number of Iterations", value=100, min_value=10, step=10)
        else:
            n_iterations = total_combos
    
    with col2:
        st.markdown("**Location & Financial**")
        st.write(f"📍 Location: {latitude:.2f}°N, {longitude:.2f}°E")
        st.write(f"📅 Project Life: {project_life} years")
        st.write(f"💰 WACC: {wacc*100:.1f}%")
    
    st.markdown("---")
    
    if st.button("🚀 Start Optimization", type="primary", use_container_width=True):
        progress_bar = st.progress(0)
        status_text = st.empty()
        
        # Create simulation function
        api = SimulationAPI(default_wacc=wacc, project_life=project_life)
        
        evaluated = [0]
        
        def simulation_func(config):
            result = api.run_hybrid_simulation(
                latitude=latitude,
                longitude=longitude,
                solar_mw=config.get('solar_mw', 0),
                wind_mw=config.get('wind_mw', 0),
                battery_mwh=config.get('battery_mwh', 0),
                project_life=project_life,
                wacc=wacc
            )
            
            evaluated[0] += 1
            progress_bar.progress(min(evaluated[0] / n_iterations, 1.0))
            status_text.text(f"Evaluating configuration {evaluated[0]}/{n_iterations}...")
            
            return {
                'lcoe': result.lcoe if result.lcoe else float('inf'),
                'annual_energy_mwh': result.total_annual_energy_mwh,
                'capacity_mw': config.get('solar_mw', 0) + config.get('wind_mw', 0),
            }
        
        status_text.text("Initializing optimizer...")
        
        opt_config = OptimizationConfig(
            algorithm=OptimizationAlgorithm(algorithm),
            n_iterations=n_iterations if algorithm != "grid_search" else 1000
        )
        
        optimizer = LCOEOptimizer(simulation_func, opt_config)
        
        if solar_max > solar_min:
            optimizer.add_variable("solar_mw", solar_min, solar_max, step=solar_step)
        if wind_max > wind_min:
            optimizer.add_variable("wind_mw", wind_min, wind_max, step=wind_step)
        if batt_max > batt_min:
            optimizer.add_variable("battery_mwh", batt_min, batt_max, step=batt_step)
        
        start_time = time.time()
        result = optimizer.run(algorithm=algorithm)
        runtime = time.time() - start_time
        
        st.session_state['optimization_result'] = result
        st.session_state['optimizer'] = optimizer
        
        progress_bar.progress(1.0)
        status_text.text(f"✅ Optimization complete! ({runtime:.1f}s)")
        
        st.success(f"**Best LCoE: ${result.best_lcoe:.2f}/MWh**")
        
        st.subheader("🏆 Optimal Configuration")
        cols = st.columns(4)
        cols[0].metric("Solar PV", f"{result.best_config.get('solar_mw', 0):.0f} MW")
        cols[1].metric("Wind", f"{result.best_config.get('wind_mw', 0):.0f} MW")
        cols[2].metric("Battery", f"{result.best_config.get('battery_mwh', 0):.0f} MWh")
        cols[3].metric("LCoE", f"${result.best_lcoe:.2f}/MWh")
        
        st.metric("Configurations Evaluated", f"{result.n_evaluations:,}")

with tab_results:
    if 'optimization_result' not in st.session_state:
        st.info("Run an optimization first to see results here.")
    else:
        result = st.session_state['optimization_result']
        
        st.subheader("📊 Optimization Results")
        
        # Convergence chart
        if result.convergence is not None and len(result.convergence) > 0:
            fig = create_convergence_chart(result.convergence, "Optimization Convergence")
            st.plotly_chart(fig, use_container_width=True)
        
        # Results scatter
        if len(result.all_results) > 0:
            df = result.all_results
            
            # Pareto chart if we have multiple objectives
            if 'capacity_mw' in df.columns:
                fig = create_pareto_chart(
                    df, 
                    x_col='lcoe', 
                    y_col='capacity_mw',
                    title="LCoE vs Capacity Trade-off"
                )
                st.plotly_chart(fig, use_container_width=True)
            
            # Top configurations
            st.subheader("🏅 Top 10 Configurations")
            valid_df = df[df['lcoe'] < float('inf')].copy()
            if len(valid_df) > 0:
                top10 = valid_df.nsmallest(10, 'lcoe')
                display_cols = [c for c in top10.columns if c not in ['valid', 'error']]
                st.dataframe(top10[display_cols].round(2), use_container_width=True)
            
            # Sensitivity
            if 'optimizer' in st.session_state:
                sensitivity = st.session_state['optimizer'].sensitivity_summary()
                if len(sensitivity) > 0:
                    st.subheader("📈 Sensitivity Analysis")
                    st.dataframe(sensitivity.round(3), use_container_width=True)
