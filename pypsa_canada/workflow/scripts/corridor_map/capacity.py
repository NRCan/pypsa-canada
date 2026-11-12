"""Planning capacity additions and expansion metadata."""

import logging
import os

import pandas as pd

from .data import read_csv_flex


def load_final_capacity_additions(unit_summary_csv: str):
    """Load cumulative additions, deduplicating corridor directions per year."""
    if not os.path.exists(unit_summary_csv):
        logging.warning(f"Unit summary CSV not found: {unit_summary_csv}")
        return {}, None, {}

    df = read_csv_flex(unit_summary_csv)

    required = {"Region", "Parameter", "Time", "Value"}
    missing = required - set(df.columns)
    if missing:
        logging.error(f"Missing columns in {unit_summary_csv}: {missing}")
        return {}, None, {}

    df["Region"] = df["Region"].astype(str).str.strip()
    df["Parameter"] = df["Parameter"].astype(str).str.strip()
    df["Time"] = pd.to_numeric(df["Time"], errors="coerce")
    df["Value"] = pd.to_numeric(df["Value"], errors="coerce").fillna(0.0)

    df = df[df["Parameter"] == "New_Transmission_Capacity"].copy()
    df = df.dropna(subset=["Time"])

    if df.empty:
        logging.info("No New_Transmission_Capacity entries found")
        return {}, None, {}

    df["Time"] = df["Time"].astype(int)
    last_year = int(df["Time"].max())

    df = df[df["Time"] <= last_year].copy()

    def canonical_region_name(region):
        region = str(region).strip()
        if "->" not in region:
            return region
        a, b = [x.strip() for x in region.split("->", 1)]
        a, b = sorted([a, b])
        return f"{a}__to__{b}"

    df["corridor_key"] = df["Region"].apply(canonical_region_name)

    grouped = (
        df.groupby(["corridor_key", "Time"], as_index=False)["Value"]
        .max()
        .sort_values(["corridor_key", "Time"])
    )

    final_added = grouped.groupby("corridor_key")["Value"].sum().to_dict()

    expansion_detail = {}
    for key, g in grouped.groupby("corridor_key"):
        g = g.sort_values("Time").copy()
        g["Cumulative_Value"] = g["Value"].cumsum()
        expansion_detail[key] = g

    return final_added, last_year, expansion_detail


def get_corridor_added_capacity(bus0: str, bus1: str, final_added: dict):
    """Look up cumulative added capacity for a canonical bus pair in MW."""
    a, b = sorted([str(bus0).strip(), str(bus1).strip()])
    key = f"{a}__to__{b}"
    return float(final_added.get(key, 0.0))


def get_corridor_added_capacity_for_year(
    bus0: str, bus1: str, year: int, expansion_detail: dict
) -> float:
    """Look up cumulative added capacity available by the given year in MW."""
    a, b = sorted([str(bus0).strip(), str(bus1).strip()])
    key = f"{a}__to__{b}"
    if key not in expansion_detail:
        return 0.0

    additions = expansion_detail[key]
    return float(additions.loc[additions["Time"] <= year, "Value"].sum())


def get_corridor_expansion_text(bus0: str, bus1: str, expansion_detail: dict):
    """Format a corridor's year-by-year expansion as HTML."""
    a, b = sorted([str(bus0).strip(), str(bus1).strip()])
    key = f"{a}__to__{b}"

    if key not in expansion_detail:
        return "No planning expansion"

    g = expansion_detail[key]

    parts = []
    for _, row in g.iterrows():
        parts.append(
            f"{int(row['Time'])}: "
            f"+{row['Value']:.1f} MW, "
            f"cumulative +{row['Cumulative_Value']:.1f} MW"
        )

    return "<br>".join(parts)


def load_metadata(post_process_folder: str) -> tuple[dict, int | str, dict]:
    """Load planning expansion metadata used in corridor popups."""
    unit_summary_path = os.path.join(post_process_folder, "unit_summary_planning.csv")
    final_added, last_year, expansion_detail = load_final_capacity_additions(
        unit_summary_path
    )

    if last_year is None:
        logging.warning("No planning year data found; using base capacities only")
        last_year = "N/A"

    return final_added, last_year, expansion_detail
