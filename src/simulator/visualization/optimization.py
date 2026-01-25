"""
Optimization visualization charts.

Charts for optimization results, Pareto fronts, and sensitivity analysis.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List, Optional


def create_pareto_chart(
    results_df: pd.DataFrame,
    x_col: str = "lcoe",
    y_col: str = "capacity_mw",
    pareto_df: Optional[pd.DataFrame] = None,
    title: str = "Optimization Results",
    height: int = 500
) -> go.Figure:
    """
    Create Pareto front visualization.
    
    Args:
        results_df: DataFrame with all optimization results.
        x_col: Column for x-axis (objective 1).
        y_col: Column for y-axis (objective 2).
        pareto_df: DataFrame with Pareto-optimal points.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    fig = go.Figure()
    
    # All points
    fig.add_trace(go.Scatter(
        x=results_df[x_col],
        y=results_df[y_col],
        mode='markers',
        name='All Configurations',
        marker=dict(
            size=8,
            color='rgba(51, 154, 240, 0.5)',
            line=dict(width=1, color='DarkSlateGrey')
        )
    ))
    
    # Pareto front
    if pareto_df is not None and len(pareto_df) > 0:
        pareto_sorted = pareto_df.sort_values(x_col)
        fig.add_trace(go.Scatter(
            x=pareto_sorted[x_col],
            y=pareto_sorted[y_col],
            mode='lines+markers',
            name='Pareto Front',
            line=dict(color='#ff6b6b', width=3),
            marker=dict(size=12, color='#ff6b6b')
        ))
    
    # Best point
    if 'lcoe' in results_df.columns:
        best_idx = results_df['lcoe'].idxmin()
        best = results_df.loc[best_idx]
        fig.add_trace(go.Scatter(
            x=[best[x_col]],
            y=[best[y_col]],
            mode='markers',
            name='Best LCOE',
            marker=dict(size=20, color='#51cf66', symbol='star')
        ))
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title=x_col.replace('_', ' ').title(),
        yaxis_title=y_col.replace('_', ' ').title(),
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    
    return fig


def create_sensitivity_tornado(
    sensitivities: pd.DataFrame,
    target: str = "lcoe",
    base_value: float = 100,
    title: str = "Sensitivity Analysis",
    height: int = 400
) -> go.Figure:
    """
    Create a tornado chart for sensitivity analysis.
    
    Args:
        sensitivities: DataFrame with 'variable', 'low_value', 'high_value' columns.
        target: Target metric name.
        base_value: Base case value.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    # Sort by impact
    if 'impact' in sensitivities.columns:
        df = sensitivities.sort_values('impact', ascending=True)
    else:
        df = sensitivities
    
    fig = go.Figure()
    
    # Low values (negative impact)
    if 'low_value' in df.columns:
        fig.add_trace(go.Bar(
            y=df['variable'],
            x=df['low_value'] - base_value,
            orientation='h',
            name='Low (-20%)',
            marker_color='#51cf66'
        ))
    
    # High values (positive impact)
    if 'high_value' in df.columns:
        fig.add_trace(go.Bar(
            y=df['variable'],
            x=df['high_value'] - base_value,
            orientation='h',
            name='High (+20%)',
            marker_color='#ff6b6b'
        ))
    
    # Base line
    fig.add_vline(x=0, line_dash="dash", line_color="gray")
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title=f"Change in {target.upper()} ($/MWh)",
        yaxis_title="Parameter",
        barmode='overlay',
        legend=dict(orientation="h", yanchor="bottom", y=1.02)
    )
    
    return fig


def create_convergence_chart(
    convergence: pd.Series,
    title: str = "Optimization Convergence",
    height: int = 300
) -> go.Figure:
    """
    Create a convergence plot for optimization.
    
    Args:
        convergence: Series of best LCOE values per iteration.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=list(range(len(convergence))),
        y=convergence.values,
        mode='lines',
        name='Best LCOE',
        line=dict(color='#339af0', width=2),
        fill='tozeroy',
        fillcolor='rgba(51, 154, 240, 0.2)'
    ))
    
    # Mark best point
    best_idx = convergence.idxmin() if hasattr(convergence, 'idxmin') else np.argmin(convergence)
    best_val = convergence.min()
    
    fig.add_trace(go.Scatter(
        x=[best_idx],
        y=[best_val],
        mode='markers',
        name=f'Best: ${best_val:.2f}/MWh',
        marker=dict(size=15, color='#51cf66', symbol='star')
    ))
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title="Iteration",
        yaxis_title="LCOE ($/MWh)",
        showlegend=True
    )
    
    return fig


def create_optimization_summary(
    result,  # OptimizationResult
    title: str = "Optimization Summary"
) -> go.Figure:
    """
    Create a comprehensive optimization summary figure.
    
    Args:
        result: OptimizationResult object.
        title: Chart title.
    
    Returns:
        Plotly Figure with subplots.
    """
    fig = make_subplots(
        rows=2, cols=2,
        subplot_titles=(
            "Configuration Distribution",
            "Convergence",
            "LCOE vs Capacity",
            "Best Configuration"
        ),
        specs=[
            [{"type": "histogram"}, {"type": "scatter"}],
            [{"type": "scatter"}, {"type": "table"}]
        ]
    )
    
    df = result.all_results
    
    # LCOE distribution
    fig.add_trace(
        go.Histogram(x=df['lcoe'], nbinsx=30, name='LCOE Distribution',
                    marker_color='#339af0'),
        row=1, col=1
    )
    
    # Convergence
    if result.convergence is not None:
        fig.add_trace(
            go.Scatter(x=list(range(len(result.convergence))),
                      y=result.convergence.values,
                      mode='lines', name='Convergence',
                      line=dict(color='#51cf66')),
            row=1, col=2
        )
    
    # Scatter plot
    if 'capacity' in df.columns or any('capacity' in c for c in df.columns):
        cap_col = 'capacity' if 'capacity' in df.columns else [c for c in df.columns if 'capacity' in c.lower()][0]
        fig.add_trace(
            go.Scatter(x=df[cap_col], y=df['lcoe'],
                      mode='markers', name='Configurations',
                      marker=dict(color='#ff6b6b', size=6, opacity=0.5)),
            row=2, col=1
        )
    
    # Best config table
    best_config = result.best_config
    fig.add_trace(
        go.Table(
            header=dict(values=['Parameter', 'Value']),
            cells=dict(values=[
                list(best_config.keys()),
                [f"{v:.2f}" if isinstance(v, float) else str(v) for v in best_config.values()]
            ])
        ),
        row=2, col=2
    )
    
    fig.update_layout(
        title=title,
        height=800,
        showlegend=False
    )
    
    return fig


def create_configuration_comparison(
    configs: List[Dict],
    labels: List[str],
    metrics: List[str] = None,
    title: str = "Configuration Comparison",
    height: int = 400
) -> go.Figure:
    """
    Create a radar chart comparing multiple configurations.
    
    Args:
        configs: List of configuration dictionaries.
        labels: Labels for each configuration.
        metrics: Metrics to compare (uses all if None).
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    if not configs:
        return go.Figure()
    
    if metrics is None:
        metrics = list(configs[0].keys())
    
    fig = go.Figure()
    
    for config, label in zip(configs, labels):
        values = [config.get(m, 0) for m in metrics]
        # Normalize to 0-100 scale
        max_vals = [max(c.get(m, 0) for c in configs) for m in metrics]
        normalized = [v / mv * 100 if mv > 0 else 0 for v, mv in zip(values, max_vals)]
        normalized.append(normalized[0])  # Close the polygon
        
        fig.add_trace(go.Scatterpolar(
            r=normalized,
            theta=metrics + [metrics[0]],
            name=label,
            fill='toself',
            opacity=0.6
        ))
    
    fig.update_layout(
        title=title,
        height=height,
        polar=dict(radialaxis=dict(visible=True, range=[0, 100])),
        showlegend=True
    )
    
    return fig
