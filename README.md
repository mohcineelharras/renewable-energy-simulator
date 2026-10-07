# Renewable Energy Simulator 2.1.0

Screening models for a solar array, a wind farm, a battery, hourly dispatch, and a pre-tax LCOE. Version 2.1.0 changes the energy accounting, so its totals are not comparable to 2.0.0.

This is not a PVsyst model and not a WindPro model. It has not been checked against either tool, against a manufacturer power curve, or against a tariff publication.

## Install and run

```bash
pip install -r requirements.txt
pip install -e ".[dev]"
streamlit run app/main.py
python -m pytest
```

`resim solar --lat 31.6 --lon -8 --capacity-mw 1` runs one solar case on synthetic weather. Add `--pvgis` to request a TMY from `re.jrc.ec.europa.eu`.

## What the models do

Solar: pvlib isotropic plane-of-array irradiance with albedo 0.25 and `apparent_zenith`, then Faiman cell temperature with u0=25 and u1=6.84, then the user temperature coefficient, then flat loss fractions, then a hard clip at AC capacity. The loss waterfall uses energy integrated over each stage, so the last stage matches the hourly energy. DC capacity is an integer module count.

Wind: nameplate, rotor, and hub height are stored per library entry. Every entry uses one idealized cubic curve (cut-in 3 m/s, rated 12 m/s, cut-out 25 m/s) unless those speeds are overridden. Hub-height speed is the neutral log-law ratio. Air density scales power and the result is clipped to nameplate. Wake and the other wind losses are flat fractions. If land, grid limit, and target capacity cannot fit one turbine, sizing raises instead of placing one.

Battery: charge and discharge limits and the state of charge use the timestep. Chemistry fills efficiency and degradation only when those fields are left empty. `thermal_losses_pct` is not applied. Unknown dispatch names raise.

Dispatch implements self-consumption, export-limit shifting, and a peak-shaving heuristic. `minimize_import` and `load_following` raise. A hybrid run with no load does not invent one: storage is idle unless an export limit is set. LCOE uses delivered energy (grid export plus load served by the project). Later years scale that year-1 delivered energy by the gross generation ratio.

Finance: one user WACC. `debt_ratio`, `cost_of_debt`, `cost_of_equity`, `corporate_tax_rate`, `depreciation_years`, and `construction_period_years` are stored and not applied. Cash flows are pre-tax. LCOE is infinite when discounted energy is zero. IRR returns no rate when the cash flows do not change sign, and the search is not capped at 100%. The floor PPA is the year-1 tariff that sets NPV to zero, including revenue escalation from year 2 and a grid charge when that option is on. `sensitivity_analysis` raises `NotImplementedError`.

Weather: synthetic solar GHI is `900 * latitude factor * sin(elevation) * seeded noise`, with DNI and DHI from pvlib's Erbs split of that GHI. Synthetic wind is Weibull shape 2 and scale `7 + abs(latitude - 45) / 10`. Both are seeded from latitude and longitude and use a 2023 UTC index. They are not climate datasets. PVGIS responses are kept only from `re.jrc.ec.europa.eu` and only up to 20 MB. A failed fetch does not invent a replacement inside `fetch_pvgis_tmy`. The API can fall back to the synthetic series and says so in `notes`.

Morocco grid charges in `MoroccoGridTariffs` are stored constants (6.68, 5.92, and 6.64 centimes/kWh, `mad_to_usd=0.10`). The UI checkbox that subtracts them is off unless selected. Nothing in this repository downloads a current tariff.

## Dependencies

Direct pins include `urllib3>=2.8.0`, `idna>=3.15`, and `jinja2>=3.1.6`. `windpowerlib`, `optuna`, and `pymoo` are not dependencies; the optimizer uses the grid, random, genetic, and SciPy Powell searches in this package. Powell does not guarantee a global minimum.

Tests run with `pytest` on the `src` layout. GitHub Actions runs that on Python 3.10, 3.11, and 3.12.
