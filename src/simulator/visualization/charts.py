"""
Chart components for renewable energy visualization.

Professional Plotly charts for simulation results.
"""

import plotly.graph_objects as go
import plotly.express as px
from plotly.subplots import make_subplots
import pandas as pd
import numpy as np
from typing import Dict, List, Optional

from simulator.core.types import LossItem


def create_loss_waterfall(
    losses: List[LossItem],
    title: str = "Energy Loss Waterfall",
    height: int = 400
) -> go.Figure:
    """
    Create a professional waterfall chart for losses.
    
    Args:
        losses: List of LossItem from simulation.
        title: Chart title.
        height: Chart height in pixels.
    
    Returns:
        Plotly Figure.
    """
    if not losses:
        return go.Figure()
    
    labels = ["Gross Energy"] + [item.stage for item in losses] + ["Net Energy"]
    
    measures = ["absolute"]
    for _ in losses:
        measures.append("relative")
    measures.append("total")

    # Deltas are stage energy, so a gain (negative loss) increases the bar
    # and the total matches net energy. Percentages of different bases are not added.
    gross = losses[0].input_energy
    if gross > 0:
        values = [gross] + [-item.loss_energy for item in losses] + [0]
        texts = [f"{gross:,.0f}"] + [f"{-item.loss_energy:,.0f}" for item in losses]
        texts.append(f"{losses[-1].output_energy:,.0f}")
        y_title = "Energy"
    else:
        values = [100.0]
        for item in losses:
            values.append(-item.loss_percent * 100)
        values.append(0)
        texts = ["100%"] + [f"{-item.loss_percent * 100:.1f}%" for item in losses]
        texts.append(f"{100 + sum(values[1:-1]):.1f}%")
        y_title = "Energy (%)"
    
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
        height=height,
        yaxis_title=y_title,
        xaxis_tickangle=-45
    )
    
    return fig


def create_production_chart(
    annual_df: pd.DataFrame,
    title: str = "Annual Production Profile",
    height: int = 400
) -> go.Figure:
    """
    Create a 30-year production chart with degradation.
    
    Args:
        annual_df: DataFrame with 'year' and 'energy_mwh' columns.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    fig = make_subplots(specs=[[{"secondary_y": True}]])
    
    year_col = 'year' if 'year' in annual_df.columns else 'Year'
    energy_col = 'energy_mwh' if 'energy_mwh' in annual_df.columns else 'Annual Energy (MWh)'
    cumulative_col = 'cumulative_mwh' if 'cumulative_mwh' in annual_df.columns else 'Cumulative Energy (MWh)'
    
    fig.add_trace(
        go.Bar(
            x=annual_df[year_col],
            y=annual_df[energy_col],
            name="Annual Energy",
            marker_color='#339af0'
        ),
        secondary_y=False
    )
    
    if cumulative_col in annual_df.columns:
        fig.add_trace(
            go.Scatter(
                x=annual_df[year_col],
                y=annual_df[cumulative_col],
                name="Cumulative",
                line=dict(color='#ff6b6b', width=2)
            ),
            secondary_y=True
        )
    
    fig.update_layout(
        title=title,
        height=height,
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        xaxis_title="Year"
    )
    fig.update_yaxes(title_text="Annual (MWh)", secondary_y=False)
    fig.update_yaxes(title_text="Cumulative (MWh)", secondary_y=True)
    
    return fig


def create_capex_pie(
    breakdown: Dict[str, float],
    title: str = "CAPEX Breakdown",
    height: int = 350
) -> go.Figure:
    """
    Create CAPEX/OPEX breakdown pie chart.
    
    Args:
        breakdown: Dict of {component: value}.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    fig = go.Figure(data=[go.Pie(
        labels=list(breakdown.keys()),
        values=list(breakdown.values()),
        hole=0.4,
        textinfo='label+percent',
        marker_colors=px.colors.qualitative.Set3
    )])
    
    fig.update_layout(
        title=title,
        height=height
    )
    
    return fig


def create_dispatch_chart(
    dispatch_df: pd.DataFrame,
    title: str = "Dispatch Profile",
    show_period: str = "week",
    height: int = 400
) -> go.Figure:
    """
    Create a dispatch visualization chart.
    
    Args:
        dispatch_df: DataFrame with dispatch data.
        title: Chart title.
        show_period: Period to show ('day', 'week', 'month', 'year')
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    # Filter to show period
    if show_period == "day":
        df = dispatch_df.iloc[:24]
    elif show_period == "week":
        df = dispatch_df.iloc[:168]
    elif show_period == "month":
        df = dispatch_df.iloc[:720]
    else:
        df = dispatch_df
    
    fig = go.Figure()
    
    # Generation (positive)
    if 'total_generation_kw' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['total_generation_kw'],
            name='Generation',
            fill='tozeroy',
            line=dict(color='#51cf66'),
            fillcolor='rgba(81, 207, 102, 0.3)'
        ))
    
    # Load
    if 'load_kw' in df.columns:
        fig.add_trace(go.Scatter(
            x=df.index,
            y=df['load_kw'],
            name='Load',
            line=dict(color='#ff6b6b', width=2)
        ))
    
    # Storage
    if 'storage_charge_kw' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index,
            y=-df['storage_charge_kw'],
            name='Charging',
            marker_color='#339af0',
            opacity=0.6
        ))
    
    if 'storage_discharge_kw' in df.columns:
        fig.add_trace(go.Bar(
            x=df.index,
            y=df['storage_discharge_kw'],
            name='Discharging',
            marker_color='#ffd43b',
            opacity=0.6
        ))
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title="Time",
        yaxis_title="Power (kW)",
        legend=dict(orientation="h", yanchor="bottom", y=1.02),
        barmode='relative'
    )
    
    return fig


def create_soc_chart(
    soc_series: pd.Series,
    title: str = "Battery State of Charge",
    show_period: str = "week",
    height: int = 300,
    min_soc: float = 0.10,
    max_soc: float = 0.90,
) -> go.Figure:
    """
    Create a battery state of charge chart.
    
    Args:
        soc_series: Series of SoC values (0-1).
        title: Chart title.
        show_period: Period to show.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    if show_period == "day":
        soc = soc_series.iloc[:24]
    elif show_period == "week":
        soc = soc_series.iloc[:168]
    elif show_period == "month":
        soc = soc_series.iloc[:720]
    else:
        soc = soc_series
    
    fig = go.Figure()
    
    fig.add_trace(go.Scatter(
        x=soc.index,
        y=soc * 100,  # Convert to percentage
        name='SoC',
        fill='tozeroy',
        line=dict(color='#339af0'),
        fillcolor='rgba(51, 154, 240, 0.3)'
    ))
    
    # Add min/max SoC lines
    fig.add_hline(y=max_soc * 100, line_dash="dash", line_color="gray",
                  annotation_text="Max SoC")
    fig.add_hline(y=min_soc * 100, line_dash="dash", line_color="gray",
                  annotation_text="Min SoC")
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title="Time",
        yaxis_title="State of Charge (%)",
        yaxis=dict(range=[0, 100])
    )
    
    return fig


def create_hourly_heatmap(
    hourly_data: pd.Series,
    title: str = "Hourly Generation Heatmap",
    height: int = 400
) -> go.Figure:
    """
    Create a heatmap of hourly data by day and hour.
    
    Args:
        hourly_data: Series with DatetimeIndex.
        title: Chart title.
        height: Chart height.
    
    Returns:
        Plotly Figure.
    """
    df = pd.DataFrame({'value': hourly_data})
    df['hour'] = df.index.hour
    df['day'] = df.index.dayofyear
    
    pivot = df.pivot_table(values='value', index='hour', columns='day', aggfunc='mean')
    
    fig = go.Figure(data=go.Heatmap(
        z=pivot.values,
        x=pivot.columns,
        y=pivot.index,
        colorscale='Viridis'
    ))
    
    fig.update_layout(
        title=title,
        height=height,
        xaxis_title="Day of Year",
        yaxis_title="Hour of Day"
    )
    
    return fig
