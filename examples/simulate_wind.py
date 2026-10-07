"""Wind screening example using the installed simulator API."""

from simulator import SimulationAPI


def run_example() -> None:
    api = SimulationAPI(allow_network=False)
    result = api.run_wind_simulation(
        latitude=35.0,
        longitude=-5.0,
        capacity_mw=3.0,
        project_life=5,
        wacc=0.06,
        turbine_model="Generic 3MW",
    )
    print(f"year 1 energy MWh: {result.wind_result.year_one_energy_mwh:.3f}")
    print(f"LCOE USD/MWh: {result.lcoe:.3f}")
    print("weather:", result.notes.get("weather"))
    model = result.wind_result.metadata.get("model", {})
    print("power curve:", model.get("power_curve"))
    print("power curve source:", model.get("power_curve_source"))


if __name__ == "__main__":
    run_example()
