import pandas as pd
import numpy as np
from abc import ABC, abstractmethod

class BaseSimulation(ABC):
    def __init__(self, name, project_life_years=30):
        self.name = name
        self.project_life_years = project_life_years
        self.annual_results = []
        self.hourly_results = {}

    @abstractmethod
    def run_year_one(self, weather_data):
        """Run the base year simulation."""
        pass

    @abstractmethod
    def apply_degradation(self, hourly_data, year):
        """Apply degradation for a specific year."""
        pass

    def run_life_cycle(self, weather_data, degradation_rate=0.005):
        """
        Run simulation for the entire project life.
        degradation_rate: annual reduction in performance (e.g., 0.005 for 0.5%)
        """
        print(f"Starting {self.project_life_years}-year simulation for {self.name}...")
        
        # Initial year
        base_hourly = self.run_year_one(weather_data)
        
        for year in range(1, self.project_life_years + 1):
            # Apply degradation: Performance = Base * (1 - rate)^(year-1)
            # Typically Year 1 is 100%, Year 2 is 100*(1-rate), etc.
            year_hourly = self.apply_degradation(base_hourly, year, degradation_rate)
            
            annual_energy = year_hourly['energy'].sum()
            self.annual_results.append({
                'Year': year,
                'Annual Energy (MWh)': annual_energy / 1000.0,
                'Degradation Factor': (1 - degradation_rate)**(year - 1)
            })
            self.hourly_results[year] = year_hourly
            
        return pd.DataFrame(self.annual_results)

    def print_summary(self):
        df = pd.DataFrame(self.annual_results)
        print("\n--- Simulation Summary ---")
        print(df.head())
        print("...")
        print(df.tail())
        total_energy = df['Annual Energy (MWh)'].sum()
        print(f"\nTotal 30-Year Production: {total_energy:,.2f} MWh")
        return df

class LossModel:
    """Helper to manage PVSyst/WindPro like loss diagrams."""
    def __init__(self):
        self.losses = {}

    def add_loss(self, label, percentage):
        """percentage as float, e.g., 0.02 for 2%"""
        self.losses[label] = percentage

    def apply_losses(self, initial_value):
        current_value = initial_value
        diagram = [("Initial", initial_value)]
        for label, p in self.losses.items():
            loss_amount = current_value * p
            current_value -= loss_amount
            diagram.append((label, current_value))
        return current_value, diagram

    def print_loss_diagram(self):
        print("\n--- Loss Diagram ---")
        for label, val in self.losses.items():
            print(f"{label:25}: -{val*100:.2f}%")
