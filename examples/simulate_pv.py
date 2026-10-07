"""Solar screening example using the installed simulator API."""

from simulator import SimulationAPI


def run_example() -> None:
    api = SimulationAPI(allow_network=False)
    result = api.run_solar_simulation(
        latitude=31.6,
        longitude=-8.0,
        capacity_mw=1.0,
        project_life=5,
        wacc=0.06,
    )
    print(f"year 1 energy MWh: {result.solar_result.year_one_energy_mwh:.3f}")
    print(f"LCOE USD/MWh: {result.lcoe:.3f}")
    print("weather:", result.notes.get("weather"))
    print("limitations:")
    for key, note in result.notes.items():
        if key != "weather":
            print(f"  {key}: {note}")


if __name__ == "__main__":
    run_example()
