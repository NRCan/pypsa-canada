"""
Shared helper functions for postprocessing PyPSA network results.

All functions are standalone (no classes) and operate on explicit parameters.
"""

import logging
import os
import time

import pandas as pd

logger = logging.getLogger(__name__)

IAMC_COLUMNS = [
    "Model",
    "Scenario",
    "Region",
    "Parameter",
    "Variable",
    "Time",
    "Value",
    "Unit",
]


def format_network(n, result_type):
    """
    Assign province/region labels to all components.

    Parameters
    ----------
    n : pypsa.Network
    result_type : str
        "Provincial" or "Nodal"

    Returns
    -------
    pypsa.Network, set
        Modified network and set of province/node identifiers.
    """
    bus_province = n.buses["province"]

    if result_type == "Provincial":
        n.generators["province"] = n.generators.bus.map(bus_province)
        n.storage_units["province"] = n.storage_units.bus.map(bus_province)
        n.stores["province"] = n.stores.bus.map(bus_province)
        n.loads["province"] = n.loads.bus.map(bus_province)
        n.lines["province"] = (
            n.lines.bus0.map(bus_province) + "->" + n.lines.bus1.map(bus_province)
        )
        n.links["province"] = (
            n.links.bus0.map(bus_province) + "->" + n.links.bus1.map(bus_province)
        )
        n.lines["bus"] = n.lines.province
        n.links["bus"] = n.links.province
        provinces = set(bus_province)
    else:
        n.generators["province"] = n.generators.bus
        n.storage_units["province"] = n.storage_units.bus
        n.stores["province"] = n.stores.bus
        n.loads["province"] = n.loads.bus
        n.lines["province"] = n.lines.bus0 + "->" + n.lines.bus1
        n.links["province"] = n.links.bus0 + "->" + n.links.bus1
        n.lines["bus"] = n.lines.province
        n.links["bus"] = n.links.province
        provinces = set(n.buses.index)

    logger.info(f"Nodes: {provinces}")
    return n, provinces


def create_templates(n):
    """
    Create IAMC-mapping templates for each component type.

    Returns
    -------
    dict
        Keys: generator_template, storage_unit_template, store_template,
              transmission_template, rev_trans_template, load_template.
    """
    templates = {}

    # Generators
    if not n.generators.empty:
        gen_tmpl = n.generators[["province", "model"]].rename(
            {"province": "Region", "model": "Variable"}, axis=1
        )
        load_shedding = gen_tmpl[gen_tmpl.index.str.contains("load shedding")].index
        gen_tmpl.loc[load_shedding, "Variable"] = "load_shedding"
        templates["generator_template"] = gen_tmpl
    else:
        templates["generator_template"] = pd.DataFrame()

    # Storage units
    if not n.storage_units.empty:
        templates["storage_unit_template"] = n.storage_units[
            ["province", "model"]
        ].rename({"province": "Region", "model": "Variable"}, axis=1)
    else:
        templates["storage_unit_template"] = pd.DataFrame()

    # Stores
    if not n.stores.empty:
        templates["store_template"] = n.stores[["province", "model"]].rename(
            {"province": "Region", "model": "Variable"}, axis=1
        )
    else:
        templates["store_template"] = pd.DataFrame()

    # Transmission (lines + links)
    units = pd.DataFrame()
    if not n.lines.empty:
        units = pd.concat([units, n.lines])
    if not n.links.empty:
        units = pd.concat([units, n.links])
    if not units.empty:
        trans_tmpl = units[["province", "carrier"]].rename(
            {"province": "Region", "carrier": "Variable"}, axis=1
        )
        rev_tmpl = trans_tmpl.copy()
        rev_tmpl["Region"] = (
            trans_tmpl.Region.str.split("->").str[1]
            + "->"
            + trans_tmpl.Region.str.split("->").str[0]
        )
        templates["transmission_template"] = trans_tmpl
        templates["rev_trans_template"] = rev_tmpl
    else:
        templates["transmission_template"] = pd.DataFrame()
        templates["rev_trans_template"] = pd.DataFrame()

    # Loads
    loads_df = n.loads.copy()
    loads_df["_load_name"] = loads_df.index
    templates["load_template"] = loads_df[["province", "_load_name"]].rename(
        {"province": "Region", "_load_name": "Variable"}, axis=1
    )
    templates["load_template"]["Variable"] = "Load"

    return templates


def format_annual_data(
    template, data, parameter, unit, year, model_name, scenario_name, agg=False
):
    """
    Format per-component annual data into IAMC rows.

    Parameters
    ----------
    template : pd.DataFrame
        Template with Region/Variable columns indexed by component.
    data : pd.Series
        Values indexed by component.
    parameter : str
    unit : str
    year : int
    model_name : str
    scenario_name : str
    agg : bool
        If True, aggregate by Region+Variable (sum, or mean for "Average" parameters).

    Returns
    -------
    pd.DataFrame
    """
    df = template.copy()
    df["Value"] = data.astype(float).round(2)
    if agg:
        if "Average" in parameter:
            df = (
                df.groupby(["Region", "Variable"])[["Value"]]
                .mean()
                .reset_index()
                .fillna(0)
            )
        else:
            df = (
                df.groupby(["Region", "Variable"])[["Value"]]
                .sum()
                .reset_index()
                .fillna(0)
            )
    else:
        df["Variable"] = df.index
        df = df.fillna(0)
    df = df[df.Value != 0]
    df["Parameter"] = parameter
    df["Unit"] = unit
    df["Time"] = year
    df["Model"] = model_name
    df["Scenario"] = scenario_name
    return df[IAMC_COLUMNS]


def calc_annual(n, year, agg, planning, templates, model_name, scenario_name):
    """
    Calculate annual metrics for generators, storage units, transmission and loads.

    Parameters
    ----------
    n : pypsa.Network
    year : int
    agg : bool
    planning : bool
    templates : dict
    model_name : str
    scenario_name : str

    Returns
    -------
    pd.DataFrame
    """
    stats = n.statistics
    result = pd.DataFrame()

    if planning:
        generators = n.generators.copy()[n.get_active_assets("Generator", year)]
        storage_units = n.storage_units.copy()[n.get_active_assets("StorageUnit", year)]
        lines = n.lines.copy()[n.get_active_assets("Line", year)]
        links = n.links.copy()[n.get_active_assets("Link", year)]
        weightings = n.snapshot_weightings.copy().loc[year]["objective"].fillna(0)
    else:
        generators = n.generators.copy()
        storage_units = n.storage_units.copy()
        lines = n.lines.copy()
        links = n.links.copy()

    def _fmt(tmpl, data, param, unit):
        return format_annual_data(
            tmpl, data, param, unit, year, model_name, scenario_name, agg
        )

    # ── GENERATORS ──
    comp = "Generator"
    template = (
        templates["generator_template"]
        .copy()
        .reindex(generators.index)
        .dropna(how="all")
    )
    annual_generation = pd.DataFrame()

    if not template.empty:
        hourly_generation = (
            stats.supply(comps=comp, groupby=False, aggregate_time=False)
            .reindex(generators.index)
            .fillna(0)
        )
        p_max = n.generators_t.p_max_pu.T.reindex(generators.index).fillna(1)
        carbon_costs = (
            n.generators_t.carbon_cost.fillna(0)
            if "carbon_cost" in n.generators_t
            else pd.DataFrame(0, index=n.snapshots, columns=generators.index)
        )
        fuel_costs = (
            n.generators_t.fuel_cost.fillna(0)
            if "fuel_cost" in n.generators_t
            else pd.DataFrame(0, index=n.snapshots, columns=generators.index)
        )
        variable_costs = (
            n.generators_t.variable_cost.fillna(0)
            if "variable_cost" in n.generators_t
            else pd.DataFrame(0, index=n.snapshots, columns=generators.index)
        )
        gen_opex = n.generators_t.marginal_cost.fillna(0)

        if planning:
            hourly_generation = hourly_generation[year].multiply(weightings, axis=1)
            p_max = p_max[year]
            carbon_costs = carbon_costs.loc[year]
            fuel_costs = fuel_costs.loc[year]
            variable_costs = variable_costs.loc[year]
            gen_opex = gen_opex.loc[year]

        # Annual generation
        annual_generation = _fmt(
            template, hourly_generation.sum(axis=1), "Annual_Generation", "MWh"
        )

        # Average resource availability
        avg_p_max = _fmt(
            template,
            p_max.mean(axis=1).round(2) * 100,
            "Average_Resource_Availability",
            "%",
        )

        # Capacity factor
        capacity_factor = (
            hourly_generation.divide(generators.p_nom_opt, axis=0).mean(axis=1).round(2)
            * 100
        )
        capacity_factor = _fmt(
            template, capacity_factor, "Average_Capacity_Factor", "%"
        )

        # Utilization
        avg_utilization = (
            hourly_generation.divide(
                p_max.multiply(generators.p_nom_opt, axis=0), axis=0
            )
            .fillna(0)
            .mean(axis=1)
            .round(2)
            * 100
        )
        avg_utilization = _fmt(template, avg_utilization, "Average_Utilization", "%")

        # Curtailment
        curtailed_energy = (
            (p_max.multiply(generators.p_nom_opt, axis=0))
            .subtract(hourly_generation)
            .round(2)
            .sum(axis=1)
            .rename("curtailed_energy")
        )
        curtailed_energy = pd.merge(
            curtailed_energy,
            generators.carrier,
            how="left",
            right_index=True,
            left_index=True,
        )
        curtailed_energy = curtailed_energy[
            curtailed_energy.carrier.str.contains("solar|wind|hydro")
        ].drop("carrier", axis=1)
        curtailed_energy = _fmt(template, curtailed_energy, "Curtailed_Energy", "MWh")

        # Emission intensity
        emission_intensity = pd.merge(
            generators[["province", "efficiency", "carrier"]],
            n.carriers["co2_emissions"],
            how="left",
            left_on="carrier",
            right_index=True,
        ).fillna(0)
        emission_intensity["emission_intensity"] = (
            emission_intensity.co2_emissions / emission_intensity.efficiency
        ).round(3)
        prov_emission_intensity = _fmt(
            template,
            emission_intensity["emission_intensity"],
            "Average_Emission_Intensity",
            "tCO2/MWh",
        )

        # Annual emissions
        annual_emissions = hourly_generation.reindex(emission_intensity.index)
        annual_emissions = annual_emissions.multiply(
            emission_intensity.emission_intensity, axis=0
        ).sum(axis=1)
        annual_emissions = _fmt(template, annual_emissions, "Emissions", "tCO2")

        # Opex
        annual_opex = (
            gen_opex.reindex(hourly_generation.columns)
            .multiply(hourly_generation.T)
            .sum(axis=0)
        )
        annual_opex = _fmt(template, annual_opex, "Generator_Opex", "$")

        # Carbon costs
        carbon_cost_result = (
            carbon_costs.reindex(hourly_generation.columns)
            .multiply(hourly_generation.T)
            .sum(axis=0)
        )
        carbon_cost_result = _fmt(template, carbon_cost_result, "Carbon_Cost", "$")

        # Fuel costs
        fuel_cost_result = (
            fuel_costs.reindex(hourly_generation.columns)
            .multiply(hourly_generation.T)
            .sum(axis=0)
        )
        fuel_cost_result = _fmt(template, fuel_cost_result, "Fuel_Cost", "$")

        # Variable O&M costs
        var_cost_result = (
            variable_costs.reindex(hourly_generation.columns)
            .multiply(hourly_generation.T)
            .sum(axis=0)
        )
        var_cost_result = _fmt(template, var_cost_result, "Variable_Cost", "$")

        result = pd.concat(
            [
                result,
                avg_p_max,
                avg_utilization,
                capacity_factor,
                curtailed_energy,
                prov_emission_intensity,
                annual_emissions,
                annual_opex,
                carbon_cost_result,
                fuel_cost_result,
                var_cost_result,
            ]
        )

    # ── STORAGE UNITS ──
    comp = "StorageUnit"
    template = (
        templates["storage_unit_template"]
        .copy()
        .reindex(storage_units.index)
        .dropna(how="all")
    )
    annual_storage_unit_out = pd.DataFrame()

    if not template.empty:
        storage_unit_out = stats.supply(comps=comp, groupby=False, aggregate_time=False)
        storage_withdrawal = stats.withdrawal(
            comps=comp, groupby=False, aggregate_time=False
        )
        store_opex = stats.opex(comps=comp, groupby=False, aggregate_time=False)
        state_of_charge = n.storage_units_t.state_of_charge.copy()
        spillage = n.storage_units_t.spill.copy()
        inflows = n.storage_units_t.inflow.copy()

        if planning:
            storage_unit_out = storage_unit_out[year].multiply(weightings, axis=1)
            storage_withdrawal = storage_withdrawal[year].multiply(weightings, axis=1)
            state_of_charge = state_of_charge.loc[year].multiply(weightings, axis=1)
            spillage = spillage.loc[year].multiply(weightings, axis=1)
            inflows = inflows.loc[year].multiply(weightings, axis=1)
            store_opex = store_opex[year].multiply(weightings, axis=1)

        state_of_charge = state_of_charge.T.reindex(storage_units.index)
        spillage = spillage.T.reindex(storage_units.index)
        inflows = inflows.T.reindex(storage_units.index)

        # Supply
        annual_storage_unit_out = _fmt(
            template, storage_unit_out.sum(axis=1), "Storage_Unit_Out", "MWh"
        )
        # Withdrawal
        annual_storage_unit_in = _fmt(
            template, storage_withdrawal.sum(axis=1), "Storage_Unit_In", "MWh"
        )

        # Negative emissions (e.g. DAC)
        su_emission_intensity = pd.merge(
            storage_units[["province", "efficiency_store", "carrier"]],
            n.carriers["co2_emissions"],
            how="left",
            left_on="carrier",
            right_index=True,
        ).fillna(0)
        su_emission_intensity = su_emission_intensity[
            su_emission_intensity.co2_emissions < 0
        ]

        has_negative_emissions = not su_emission_intensity.empty
        if has_negative_emissions:
            su_emission_intensity["emission_intensity"] = (
                su_emission_intensity.co2_emissions
                * su_emission_intensity.efficiency_store
            ).round(3)
            su_prov_emission = _fmt(
                template,
                su_emission_intensity["emission_intensity"],
                "Average_Emission_Intensity",
                "tCO2/MWh",
            )
            su_annual_emissions = storage_withdrawal.reindex(
                su_emission_intensity.index
            )
            su_annual_emissions = su_annual_emissions.multiply(
                su_emission_intensity.emission_intensity, axis=0
            ).sum(axis=1)
            su_DAC_revenue = su_annual_emissions.multiply(
                storage_units.marginal_cost_storage, axis=0
            )
            su_DAC_revenue = _fmt(template, su_DAC_revenue, "DAC_revenue", "$")
            su_annual_emissions = _fmt(
                template, su_annual_emissions, "Removed_Emissions", "tCO2"
            )

        # Average SoC
        max_storage = storage_units.p_nom_opt.copy().multiply(storage_units.max_hours)
        storage_unit_soc = (
            state_of_charge.divide(max_storage, axis=0).fillna(0).mean(axis=1) * 100
        )
        storage_unit_soc = _fmt(
            template, storage_unit_soc, "Average_State_of_Charge", "%"
        )

        # Spillage
        spillage_result = _fmt(
            template, spillage.sum(axis=1), "Storage_Unit_Spill", "MWh"
        )

        # Inflows
        inflows_result = _fmt(
            template, inflows.sum(axis=1), "Storage_Unit_Inflows", "MWh"
        )

        # Opex
        annual_store_opex = _fmt(template, store_opex.sum(axis=1), "Storage_Opex", "$")

        result = pd.concat(
            [
                result,
                annual_storage_unit_out,
                annual_storage_unit_in,
                storage_unit_soc,
                spillage_result,
                inflows_result,
                annual_store_opex,
            ]
        )
        if has_negative_emissions:
            result = pd.concat(
                [result, su_prov_emission, su_annual_emissions, su_DAC_revenue]
            )

    # ── TRANSMISSION ──
    comp = []
    units = pd.DataFrame()
    if not lines.empty:
        comp += ["Line"]
        units = pd.concat([units, n.lines])
    if not links.empty:
        comp += ["Link"]
        units = pd.concat([units, n.links])
    template = (
        templates["transmission_template"].copy().reindex(units.index).dropna(how="all")
    )
    rev_template = (
        templates["rev_trans_template"].copy().reindex(units.index).dropna(how="all")
    )

    if not template.empty:
        transmission_hourly = stats.transmission(
            comps=comp, groupby=False, aggregate_time=False
        )
        if planning:
            transmission_hourly = transmission_hourly[year].multiply(weightings, axis=1)

        transmission_hourly.index.names = ["component", "Line"]
        transmission_hourly = (
            transmission_hourly.reset_index()
            .set_index("Line")
            .drop("component", axis=1)
        )

        annual_transmission = _fmt(
            template, transmission_hourly.sum(axis=1), "Net_Line_Flow", "MWh"
        )

        # Capacity for utilization
        if len(comp) == 1:
            if "Line" in comp:
                capacity = lines.copy()
                rev_cap = pd.DataFrame()
            elif "Link" in comp:
                capacity = links.copy()
                rev_cap = links.copy()
                capacity["s_nom_opt"] = capacity["p_nom_opt"]
                rev_cap.loc[:, "s_nom_opt"] = (
                    rev_cap["p_nom_opt"]
                    .multiply(rev_cap["p_min_pu"], axis=0)
                    .multiply(-1)
                )
        else:
            capacity = pd.concat([lines, links])
            rev_cap = links.copy()
            rev_cap.loc[:, "p_nom_opt"] = (
                rev_cap["p_nom_opt"].multiply(rev_cap["p_min_pu"], axis=0).multiply(-1)
            )
            rev_cap = pd.concat([lines, rev_cap])
            capacity["s_nom_opt"] = capacity["s_nom_opt"].fillna(capacity["p_nom_opt"])
            rev_cap["s_nom_opt"] = rev_cap["s_nom_opt"].fillna(rev_cap["p_nom_opt"])

        hourly_flows = transmission_hourly.where(transmission_hourly > 0).fillna(0)
        flow = _fmt(template, hourly_flows.sum(axis=1), "Line_Flow", "MWh")
        line_util = (
            hourly_flows.divide(capacity["s_nom_opt"].replace(0, pd.NA), axis=0)
            .fillna(0)
            .mean(axis=1)
            * 100
        )
        line_util = _fmt(template, line_util, "Line_Utilization", "%")
        trans_cost = (
            transmission_hourly.multiply(links.marginal_cost, axis=0)
            .fillna(0)
            .sum(axis=1)
        )
        trans_cost = _fmt(template, trans_cost, "Transmission_Cost", "$")

        result = pd.concat([result, annual_transmission, flow, line_util, trans_cost])

        # Reverse flows
        if not rev_cap.empty:
            rev_hourly_flows = (
                transmission_hourly.where(transmission_hourly < 0)
                .fillna(0)
                .multiply(-1)
            )
            flow_rev = _fmt(
                rev_template, rev_hourly_flows.sum(axis=1), "Line_Flow", "MWh"
            )
            rev_util = (
                rev_hourly_flows.divide(rev_cap["s_nom_opt"].replace(0, pd.NA), axis=0)
                .fillna(0)
                .mean(axis=1)
                * 100
            )
            rev_util = _fmt(rev_template, rev_util, "Line_Utilization", "%")
            result = pd.concat([result, flow_rev, rev_util])

    # ── GENERATION MIX ──
    if not annual_generation.empty:
        if not annual_storage_unit_out.empty:
            hydro_out = annual_storage_unit_out[
                annual_storage_unit_out.Variable == "hydro_storage"
            ]
            hydro_out = hydro_out.copy()
            hydro_out.loc[:, "Parameter"] = "Annual_Generation"
            annual_generation = pd.concat([annual_generation, hydro_out])

        total_gen = (
            annual_generation.rename({"Value": "Total"}, axis=1)
            .groupby("Region")["Total"]
            .sum()
        )
        total_gen = pd.merge(
            annual_generation, total_gen, how="left", left_on="Region", right_index=True
        )
        total_gen["Value"] = total_gen["Value"] / total_gen["Total"] * 100
        total_gen = total_gen.drop("Total", axis=1)
        total_gen["Parameter"] = "Annual_Generation_Mix"
        total_gen["Unit"] = "%"
        result = pd.concat([result, total_gen, annual_generation])

    # ── LOADS ──
    template = templates["load_template"].copy()
    hourly_loads = n.loads_t.p_set.copy()
    if planning:
        hourly_loads = hourly_loads.loc[year].multiply(weightings, axis=0)
    hourly_loads = hourly_loads.T

    annual_load = _fmt(template, hourly_loads.sum(axis=1), "Annual_Load", "MWh")
    peak_load = _fmt(template, hourly_loads.max(axis=1), "Peak_Load", "MWh")
    result = pd.concat([result, annual_load, peak_load])

    return result.fillna(0)


def calc_energy_balance(n, year, planning=False):
    """
    Calculate hourly energy balance by province.

    Returns
    -------
    pd.DataFrame
        Transposed hourly balance (rows=timesteps, columns=carrier-province).
    """
    stats = n.statistics
    result = pd.DataFrame()
    group = ["province", "carrier"]

    if planning:
        generators = n.generators[n.get_active_assets("Generator", year)]
        storage_units = n.storage_units[n.get_active_assets("StorageUnit", year)]
        lines = n.lines[n.get_active_assets("Line", year)]
        links = n.links[n.get_active_assets("Link", year)]
    else:
        generators = n.generators
        storage_units = n.storage_units
        lines = n.lines
        links = n.links

    # Generation
    if not generators.empty:
        generation = stats.supply(
            comps="Generator", groupby=group, aggregate_time=False
        )
        if planning:
            generation = generation.T.loc[year].T
        generation = generation.fillna(0).reset_index().set_index("carrier")
        generation.index += "_generation"
        result = pd.concat([result, generation])

    # Storage
    if not storage_units.empty:
        storage_supply = stats.supply(
            comps="StorageUnit", groupby=group, aggregate_time=False
        )
        storage_withdrawal = stats.withdrawal(
            comps="StorageUnit", groupby=group, aggregate_time=False
        )
        if planning:
            storage_supply = storage_supply.T.loc[year].T
            storage_withdrawal = storage_withdrawal.T.loc[year].T
        storage_supply = storage_supply.fillna(0).reset_index().set_index("carrier")
        storage_supply.index += "_storage_out"
        storage_withdrawal *= -1
        storage_withdrawal = (
            storage_withdrawal.fillna(0).reset_index().set_index("carrier")
        )
        storage_withdrawal.index += "_storage_in"
        result = pd.concat([result, storage_supply, storage_withdrawal])

    # Transmission
    comp = []
    if not lines.empty:
        comp += ["Line"]
    if not links.empty:
        comp += ["Link"]
    if comp:
        bus0_trans = stats.transmission(
            comps=comp, groupby=["bus0", "bus1"], aggregate_time=False
        )
        if planning:
            bus0_trans = bus0_trans.T.loc[year].T
        if not bus0_trans.empty:
            bus0_trans = bus0_trans.reset_index()
            bus0_trans = (
                bus0_trans.rename({"bus0": "province", "bus1": "carrier"}, axis=1)
                .set_index(["province", "carrier"])
                .drop("component", axis=1)
                .fillna(0)
            )
            bus0_trans *= -1
            bus1_trans = bus0_trans * -1
            bus1_trans = bus1_trans.reset_index()
            bus1_trans[["province", "carrier"]] = bus1_trans[["carrier", "province"]]
            bus0_trans = bus0_trans.reset_index().set_index("carrier")
            bus1_trans = bus1_trans.set_index("carrier")
            transmission = pd.concat([bus0_trans, bus1_trans])
            # Map bus names to the same grouping keys used by generators/loads,
            # which format_network sets to province codes (Provincial) or bus
            # names (Nodal).  This normalises transmission column names so they
            # match the file keys used by save_prov_energy_balance and drops
            # intra-group flows (e.g. intra-provincial in Provincial mode).
            bus_to_key: dict = {}
            for comp in (n.generators, n.storage_units, n.loads):
                if (
                    not comp.empty
                    and "province" in comp.columns
                    and "bus" in comp.columns
                ):
                    bus_to_key.update(zip(comp["bus"], comp["province"]))
            if bus_to_key:
                transmission["province"] = transmission["province"].map(
                    lambda b: bus_to_key.get(b, b)
                )
                transmission.index = pd.Index(
                    [bus_to_key.get(c, c) for c in transmission.index],
                    name=transmission.index.name,
                )
                transmission = transmission[
                    transmission.index != transmission["province"]
                ]
            transmission.index += "_transmission_flow"
            result = pd.concat([result, transmission])

    # Loads
    loads = n.loads[["province"]]
    loads_p_set = n.loads_t.p_set
    if planning:
        loads_p_set = loads_p_set.loc[year]
    loads = pd.merge(loads, loads_p_set.T * -1, left_index=True, right_index=True)

    df = pd.concat([result, loads]).fillna(0)
    df.index += "-" + df.province
    df = df.drop("province", axis=1)
    df = df.groupby(df.index).sum()
    return df.T


def calc_storage_balance(n, year, planning=False):
    """
    Calculate per-unit storage balance (SoC, inflow, spill, charge, discharge).

    Returns
    -------
    pd.DataFrame
        Rows=timesteps, columns=unit.metric.
    """
    if planning:
        storage_units = n.storage_units[n.get_active_assets("StorageUnit", year)]
    else:
        storage_units = n.storage_units

    SoC = n.storage_units_t.state_of_charge
    inflow = n.storage_units_t.inflow
    spill = n.storage_units_t.spill
    charge = n.storage_units_t.p_store
    discharge = n.storage_units_t.p_dispatch

    if planning:
        SoC = SoC.loc[year]
        inflow = inflow.loc[year]
        spill = spill.loc[year]
        charge = charge.loc[year]
        discharge = discharge.loc[year]

    SoC = SoC.T.reindex(storage_units.index).T
    inflow = inflow.T.reindex(storage_units.index).T
    spill = spill.T.reindex(storage_units.index).T
    charge = charge.T.reindex(storage_units.index).T
    discharge = discharge.T.reindex(storage_units.index).T

    data = pd.DataFrame()
    for storage_unit in storage_units.index:
        if SoC.empty:
            continue
        unit_SoC = SoC[storage_unit]
        unit_inflow = (
            inflow[storage_unit]
            if storage_unit in inflow.columns
            else unit_SoC.copy() * 0
        )
        unit_spill = (
            spill[storage_unit]
            if storage_unit in spill.columns
            else unit_SoC.copy() * 0
        )

        if (
            storage_unit in charge.columns
            and storage_units.loc[storage_unit, "efficiency_store"]
        ):
            unit_charge = charge[storage_unit].multiply(
                storage_units.loc[storage_unit, "efficiency_store"]
            )
        else:
            unit_charge = unit_SoC.copy() * 0

        unit_discharge = (
            discharge[storage_unit]
            / storage_units.loc[storage_unit, "efficiency_dispatch"]
        )

        df = pd.DataFrame(
            [unit_SoC, unit_inflow, unit_spill, unit_charge, unit_discharge],
            index=["State_of_charge", "Inflow", "Spill", "Charge", "Discharge"],
        )
        df.index = storage_unit + "." + df.index
        data = pd.concat([data, df])
    return data.T


def save_prov_energy_balance(df, results_path, result_type, provinces):
    """
    Save per-province hourly energy balance CSVs.

    Parameters
    ----------
    df : pd.DataFrame
    results_path : str
    result_type : str
    provinces : set
    """
    start_time = time.perf_counter()
    prov_balance_path = os.path.join(results_path, f"{result_type}_energy_balance")
    os.makedirs(prov_balance_path, exist_ok=True)
    df = df.fillna(0).T
    df["province"] = df.index.str.split("-").str[-1]
    df.index = df.index.str.split("-").str[0]
    for prov in provinces:
        prov_df = df[df.province == prov].drop("province", axis=1).T
        path_replace = prov.replace("/", "_")
        path = os.path.join(prov_balance_path, f"{path_replace}_hourly.csv")
        prov_df.loc[:, (prov_df != 0).any(axis=0)].to_csv(path)
    logger.info(
        f"Saved hourly {result_type} energy balance ({round(time.perf_counter() - start_time, 3)} s)"
    )


def save_storage_balance(df, results_path):
    """
    Save per-unit hourly storage balance CSVs.

    Parameters
    ----------
    df : pd.DataFrame
    results_path : str
    """
    if df.empty:
        return
    start_time = time.perf_counter()
    storage_balance_path = os.path.join(results_path, "storage_unit_balance")
    os.makedirs(storage_balance_path, exist_ok=True)
    df = df.fillna(0).T
    df["unit"] = df.index.str.rsplit(".", n=1).str[0]
    df.index = df.index.str.rsplit(".", n=1).str[-1]
    for unit in df.unit.unique():
        unit_df = df[df.unit == unit].drop("unit", axis=1).T.fillna(0)
        unit_df = unit_df[(unit_df != 0).any(axis=1)]
        if not unit_df.empty:
            unit_df.loc[:, (unit_df != 0).any(axis=0)].to_csv(
                os.path.join(storage_balance_path, f"{unit}_hourly.csv")
            )
    logger.info(
        f"Saved hourly storage balance ({round(time.perf_counter() - start_time, 3)} s)"
    )


def manual_capacity_calc(n, component):
    """
    Compute active capacity per investment period directly from optimal sizing.

    Parameters
    ----------
    n : pypsa.Network
    component : str
        "Line", "Link", "Store", "Generator", "StorageUnit"

    Returns
    -------
    pd.DataFrame
        Rows=components, columns=investment periods.
    """
    if component == "Line":
        return pd.concat(
            {
                period: n.get_active_assets(component, period)
                * n.static(component).s_nom_opt
                for period in n.investment_periods
            },
            axis=1,
        )
    elif component == "Store":
        return pd.concat(
            {
                period: n.get_active_assets(component, period)
                * n.static(component).e_nom_opt
                for period in n.investment_periods
            },
            axis=1,
        )
    else:
        return pd.concat(
            {
                period: n.get_active_assets(component, period)
                * n.static(component).p_nom_opt
                for period in n.investment_periods
            },
            axis=1,
        )
