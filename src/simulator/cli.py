"""Command line entry point for a solar screening case."""

from __future__ import annotations

import argparse
import json

from simulator import __version__
from simulator.api import SimulationAPI


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="resim",
        description=(
            "Screening-level renewable energy simulation. "
            "Not a PVsyst or WindPro model."
        ),
    )
    parser.add_argument("--version", action="version", version=f"resim {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    solar = sub.add_parser("solar", help="Run one solar screening case")
    solar.add_argument("--lat", type=float, required=True)
    solar.add_argument("--lon", type=float, required=True)
    solar.add_argument("--capacity-mw", type=float, default=1.0)
    solar.add_argument("--years", type=int, default=1)
    solar.add_argument("--wacc", type=float, default=0.06)
    solar.add_argument(
        "--pvgis",
        action="store_true",
        help="Request a PVGIS TMY. Without this flag the weather is synthetic.",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "solar":
        api = SimulationAPI(allow_network=bool(args.pvgis))
        result = api.run_solar_simulation(
            latitude=args.lat,
            longitude=args.lon,
            capacity_mw=args.capacity_mw,
            project_life=args.years,
            wacc=args.wacc,
        )
        payload = {
            "version": __version__,
            "year_one_energy_mwh": result.solar_result.year_one_energy_mwh,
            "lcoe_usd_per_mwh": result.lcoe,
            "notes": result.notes,
            "model": result.solar_result.metadata.get("model", {}),
            "limitations": [
                "Isotropic plane-of-array model with albedo 0.25.",
                "IAM, inverter, shading, and availability are flat user fractions.",
                "Synthetic weather is a seeded schematic, not a climate dataset.",
                "LCOE is pre-tax and uses a single WACC. Debt and depreciation are not applied.",
            ],
        }
        print(json.dumps(payload, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
