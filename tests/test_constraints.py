"""
Pytest-based tests for PyPSA constraints

Tests individual constraint functions and validates that solved models respect constraints.
Run with: pytest tests/ -v
Run only fast tests: pytest tests/ -m "not slow"
Run specific test: pytest tests/test_constraints.py::test_spilling_variable_added -v

Updated: February 12, 2026 - Aligned with migrated constraint implementations
"""

import pytest
import pandas as pd
import numpy as np
import os

# Imports from constraint modules (path set up by conftest.py)
from constraints.generic_constraints import (
    add_spilling_variable,
    add_stop_prod_constraint,
    add_bidirection_link_constraint,
    prevent_spill_if_not_fully_charged,
    CER_generator_grouping,
    aggregate_generators_into_group,
)
from constraints.planning_constraints import (
    add_CER_constraint_planning,
    add_planning_reserve_margin,
    add_emission_constraint_planning,
    component_capacity_expansion_constraint,
)
from constraints.dispatch_constraints import (
    distribute_CER_hours_dispatch,
    add_CER_constraint_dispatch,
)

# os.environ['PYPSA_CUSTOM_DATA_FOLDER'] = 'my_value_as_string'
# # ============================================================================
# # SPILLING VARIABLE TESTS
# # ============================================================================

# @pytest.mark.unit
# @pytest.mark.planning
# def test_spilling_variable_added(network_with_storage):
#     """Test that spilling variable is added to the model"""
#     network = network_with_storage
#     network.optimize.create_model()
    
#     # Test with explicit snapshots
#     add_spilling_variable(network, network.snapshots)
    
#     assert "GlobalConstraint-StorageUnit_spilling" in network.model.variables, \
#         "Spilling variable not added to model"
#     var_shape = network.model.variables["GlobalConstraint-StorageUnit_spilling"].shape
#     assert var_shape[0] > 0, "Spilling variable should have timesteps"
    

# @pytest.mark.unit
# @pytest.mark.planning
# def test_spilling_variable_default_snapshots(network_with_storage):
#     """Test that spilling variable works with default snapshots parameter"""
#     network = network_with_storage
#     network.optimize.create_model()
    
#     # Test with None (should use network.snapshots)
#     add_spilling_variable(network, None)
    
#     assert "GlobalConstraint-StorageUnit_spilling" in network.model.variables


# @pytest.mark.slow
# @pytest.mark.planning
# def test_spilling_variable_validated(network_with_storage):
#     """Test that spilling values are non-negative after solving"""
#     network = network_with_storage
#     network.optimize.create_model()
#     add_spilling_variable(network, network.snapshots)
    
#     status = network.optimize.solve_model()
#     assert status[0] == "ok", f"Model failed to solve: {status}"
    
#     spilling_var = network.model.variables["GlobalConstraint-StorageUnit_spilling"]
#     spilling_values = spilling_var.solution
    
#     assert (spilling_values >= -1e-6).all(), \
#         f"Spilling variable has negative values: min={spilling_values.min():.4f}"


# ============================================================================
# STOP PRODUCTION CONSTRAINT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
@pytest.mark.parametrize("carrier,period", [
    ("gas_CC", 2030),
    ("gas_CC", 2035),
])
def test_stop_production_constraint_added(minimal_planning_network, carrier, period):
    """Test that stop production constraint is added"""
    network = minimal_planning_network
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    network.optimize.create_model()
    add_stop_prod_constraint(network, snapshots, [carrier])
    
    constraint_name = f"GlobalConstraint-Stop_production_{carrier}"
    assert any(constraint_name in str(c) for c in network.model.constraints), \
        f"Stop production constraint for {carrier} not added"


@pytest.mark.slow
@pytest.mark.planning
@pytest.mark.parametrize("carrier,period", [
    ("gas_CC", 2030),
])
def test_stop_production_validated(minimal_planning_network, carrier, period):
    """Test that stopped generators have zero production after solving"""
    network = minimal_planning_network
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    network.optimize.create_model()
    add_stop_prod_constraint(network, snapshots, [carrier])
    
    status = network.optimize.solve_model()
    assert status[0] == "ok", f"Model failed to solve: {status}"
    
    # Validate zero production
    gens_to_stop = network.generators[network.generators.carrier.isin([carrier])]
    assert not gens_to_stop.empty, f"No generators found with carrier {carrier}"
    
    gen_dispatch = network.generators_t.p[gens_to_stop.index].loc[snapshots]
    max_production = gen_dispatch.max().max()
    
    assert max_production <= 1e-4, \
        f"Stopped generators still producing: max={max_production:.4f} MW"


# ============================================================================
# BIDIRECTIONAL LINK CONSTRAINT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
def test_bidirectional_link_constraint_added(network_with_links):
    """Test that bidirectional link constraint is added"""
    network = network_with_links
    links_dict = {"test_connection": ["link_forward", "link_reverse"]}
    
    network.optimize.create_model()
    add_bidirection_link_constraint(network, links_dict)
    
    assert any("Pnom_equality" in str(c) or "Bidirectionnality" in str(c) 
               for c in network.model.constraints), \
        "Bidirectional link constraint not added"


@pytest.mark.slow
@pytest.mark.planning
def test_bidirectional_link_validated(network_with_links):
    """Test that forward and reverse link capacities are equal after solving"""
    network = network_with_links
    links_dict = {"test_connection": ["link_forward", "link_reverse"]}
    
    network.optimize.create_model()
    add_bidirection_link_constraint(network, links_dict)
    
    status = network.optimize.solve_model()
    assert status[0] == "ok", f"Model failed to solve: {status}"
    
    # Validate equal capacities
    forward_cap = network.links.loc["link_forward", "p_nom_opt"]
    reverse_cap = network.links.loc["link_reverse", "p_nom_opt"]
    
    assert abs(forward_cap - reverse_cap) <= 1e-3, \
        f"Link capacities not equal: forward={forward_cap:.2f} != reverse={reverse_cap:.2f}"


# ============================================================================
# PREVENT SPILL CONSTRAINT TESTS
# ============================================================================

# @pytest.mark.unit
# @pytest.mark.planning
# def test_prevent_spill_constraint_added(network_with_storage):
#     """Test that prevent spill constraint is added"""
#     network = network_with_storage
#     M = 2000
    
#     network.optimize.create_model()
#     # Must add spilling variable first
#     add_spilling_variable(network, snapshots=network.snapshots)
#     prevent_spill_if_not_fully_charged(network, network.snapshots, M)
    
#     # Check for specific constraint names
#     constraint_names = [str(c) for c in network.model.constraints]
#     assert any("spill_seq_max_inflow" in name for name in constraint_names), \
#         "Spill max inflow constraint not added"
#     assert any("spill_iff_fully_charged" in name for name in constraint_names), \
#         "Spill iff fully charged constraint not added"


# @pytest.mark.slow
# @pytest.mark.planning
# def test_prevent_spill_validated(network_with_storage):
#     """Test that spilling only occurs when storage is fully charged"""
#     network = network_with_storage
#     M = 2000
    
#     network.optimize.create_model()
#     # Must add spilling variable first
#     add_spilling_variable(network, snapshots=network.snapshots)
#     prevent_spill_if_not_fully_charged(network, network.snapshots, M)
    
#     status = network.optimize.solve_model()
#     assert status[0] == "ok", f"Model failed to solve: {status}"
    
#     # Validate spilling behavior
#     if "GlobalConstraint-StorageUnit_spilling" not in network.model.variables:
#         pytest.skip("Spilling variable not in model (may be no storage with inflow)")
    
#     spilling_var = network.model.variables["GlobalConstraint-StorageUnit_spilling"]
#     spilling_values = spilling_var.solution
    
#     violations = 0
#     for su in network.storage_units.index:
#         if su not in network.storage_units_t.state_of_charge.columns:
#             continue
        
#         soc = network.storage_units_t.state_of_charge[su]
#         max_soc = network.storage_units.loc[su, "p_nom"] * network.storage_units.loc[su, "max_hours"]
        
#         if isinstance(spilling_values, pd.DataFrame) and su in spilling_values.columns:
#             spill = spilling_values[su]
#         elif isinstance(spilling_values, pd.Series):
#             spill = spilling_values
#         else:
#             continue
        
#         spilling_times = spill > 1e-4
#         if spilling_times.any():
#             soc_at_spill = soc[spilling_times]
#             not_full = soc_at_spill < (max_soc - 1e-2)
#             violations += not_full.sum()
    
#     assert violations == 0, \
#         f"Found {violations} violations: spilling when not fully charged"


# ============================================================================
# CER PLANNING CONSTRAINT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
def test_cer_planning_constraint_added(minimal_planning_network, cer_config):
    """Test that CER planning constraint is added"""
    network = minimal_planning_network
    period = cer_config["year"]
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    # Get CER generators
    CER_generators, _, CER_group_list = CER_generator_grouping(
        network, cer_config, period, "planning"
    )
    
    if CER_generators.empty:
        pytest.skip("No CER generators found")
    
    network.optimize.create_model()
    add_CER_constraint_planning(
        cer_config, network.model, network, snapshots,
        CER_group_list, CER_generators, period
    )
    
    assert any("CER_constraint" in str(c) for c in network.model.constraints), \
        "CER planning constraint not added"


@pytest.mark.slow
@pytest.mark.planning
def test_cer_planning_validated(minimal_planning_network, cer_config):
    """Test that CER generators respect the limit after solving"""
    network = minimal_planning_network
    period = cer_config["year"]
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    # Get CER generators
    CER_generators, _, CER_group_list = CER_generator_grouping(
        network, cer_config, period, "planning"
    )
    
    if CER_generators.empty:
        pytest.skip("No CER generators found")
    
    network.optimize.create_model()
    add_CER_constraint_planning(
        cer_config, network.model, network, snapshots,
        CER_group_list, CER_generators, period
    )
    
    status = network.optimize.solve_model()
    assert status[0] == "ok", f"Model failed to solve: {status}"
    
    # Validate CER limit
    limit_pct = cer_config["values"]["limit"][period]
    
    cer_gen_dispatch = network.generators_t.p[CER_generators.index].loc[snapshots]
    total_cer_generation = cer_gen_dispatch.sum().sum()
    
    all_gen_dispatch = network.generators_t.p.loc[snapshots]
    total_generation = all_gen_dispatch.sum().sum()
    
    if total_generation > 0:
        actual_cer_pct = (total_cer_generation / total_generation) * 100
        assert actual_cer_pct <= limit_pct + 1.0, \
            f"CER limit violated: {actual_cer_pct:.2f}% > {limit_pct}%"
    else:
        pytest.skip("No generation in period")


# ============================================================================
# RESERVE MARGIN CONSTRAINT TESTS
# ============================================================================

@pytest.mark.slow
@pytest.mark.planning
@pytest.mark.parametrize("margin", [1.1, 1.2, 1.5])
def test_reserve_margin_validated(minimal_planning_network, reserve_margin_config, margin):
    """Test that reserve margin constraint is satisfied after solving"""
    
    network = minimal_planning_network
    config = reserve_margin_config.copy()
    config["margin"] = margin
    period = config["period"]
    
    network.optimize.create_model()
    data_folder = os.environ['PYPSA_CUSTOM_DATA_FOLDER']
    filepath = os.path.join(data_folder, "constraints", "capacity_values_placeholder.csv")
    try:
        add_planning_reserve_margin(
            network, period, 
            config["province"], config["margin"], filepath
        )
    except FileNotFoundError as e:
        if "capacity_values_placeholder.csv" in str(e):
            pytest.skip("capacity_values_placeholder.csv not found - expected for this constraint")
        raise
    
    status = network.optimize.solve_model()
    assert status[0] == "ok", f"Model failed to solve: {status}"
    
    # Validate reserve margin
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    peak_load = network.loads_t.p_set.loc[snapshots].sum(axis=1).max()
    
    total_capacity = 0
    for gen in network.generators.index:
        if network.generators.loc[gen, "p_nom_extendable"]:
            total_capacity += network.generators.loc[gen, "p_nom_opt"]
        else:
            total_capacity += network.generators.loc[gen, "p_nom"]
    
    required_capacity = peak_load * margin
    actual_margin = total_capacity / peak_load if peak_load > 0 else float('inf')
    
    assert total_capacity >= required_capacity - 1e-2, \
        f"Reserve margin not met: {actual_margin:.2f} < {margin:.2f}"


# ============================================================================
# EMISSIONS CONSTRAINT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
def test_emissions_constraint_added(minimal_planning_network, emissions_config):
    """Test that emissions constraint is added"""
    network = minimal_planning_network
    period = emissions_config["period"]
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    network.optimize.create_model()
    add_emission_constraint_planning(
        network, snapshots,
        emissions_config["limit"], period
    )
    
    assert any("Emissions_Limit" in str(c) for c in network.model.constraints), \
        "Emissions constraint not added"


@pytest.mark.slow
@pytest.mark.planning
@pytest.mark.parametrize("emissions_limit", [50, 100, 200])
def test_emissions_validated(minimal_planning_network, emissions_config, emissions_limit):
    """Test that emissions are below the limit after solving"""
    network = minimal_planning_network
    config = emissions_config.copy()
    config["limit"] = emissions_limit
    period = config["period"]
    snapshots = network.snapshots[network.snapshots.get_level_values(0) == period]
    
    network.optimize.create_model()
    add_emission_constraint_planning(
        network, snapshots,
        config["limit"], period
    )
    
    status = network.optimize.solve_model()
    assert status[0] == "ok", f"Model failed to solve: {status}"
    
    # Validate emissions
    gen_dispatch = network.generators_t.p.loc[snapshots]
    
    total_emissions = 0
    for gen in network.generators.index:
        if gen not in gen_dispatch.columns:
            continue
        
        carrier = network.generators.loc[gen, "carrier"]
        if carrier in network.carriers.index:
            co2_emissions = network.carriers.loc[carrier, "co2_emissions"]
            gen_energy = gen_dispatch[gen].sum()
            gen_emissions = gen_energy * co2_emissions
            total_emissions += gen_emissions
    
    total_emissions_Mt = total_emissions / 1e6
    tolerance = emissions_limit * 0.001
    
    assert total_emissions_Mt <= emissions_limit + tolerance, \
        f"Emissions limit violated: {total_emissions_Mt:.4f} > {emissions_limit} MtCO2eq"


# ============================================================================
# COMPONENT CAPACITY EXPANSION CONSTRAINT TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
def test_component_capacity_expansion_requires_csv():
    """Test that component_capacity_expansion_constraint handles missing CSV gracefully"""
    import pypsa
    network = pypsa.Network()
    network.set_investment_periods([2030])
    
    # Add minimal components to avoid empty network
    network.add("Bus", "test_bus")
    network.add("Generator", "test_gen",
                bus="test_bus",
                p_nom=100,
                carrier="test",
                marginal_cost=50,
                p_nom_extendable=True)
    
    network.optimize.create_model()
    
    data_folder = os.environ['PYPSA_CUSTOM_DATA_FOLDER']
    filepath = os.path.join(data_folder, "constraints", "custom_constraints.csv")

    result = component_capacity_expansion_constraint(
        network, filepath
    )
    # Function should complete without error
    assert result == 0 or result is None
    # except FileNotFoundError:
    #     # Also acceptable - constraint can't work without CSV
    #     pytest.skip("CSV file not found - expected behavior")


# ============================================================================
# CER GENERATOR GROUPING TESTS
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
@pytest.mark.parametrize("aggregation", ["provincial", "individual"])
def test_cer_generator_grouping(minimal_planning_network, cer_config, aggregation):
    """Test CER generator grouping with different aggregation methods"""
    network = minimal_planning_network
    config = cer_config.copy()
    config["aggregation"] = aggregation
    period = config["year"]
    
    CER_generators, CER_group_budget, CER_group_list = CER_generator_grouping(
        network, config, period, "planning"
    )
    
    # May be empty if no generators meet criteria
    if not CER_generators.empty:
        assert "group" in CER_generators.columns, "Group column not added"
        assert CER_group_list is not None, "Group list not returned"
        
        if aggregation == "provincial":
            # Groups should be 2-char province codes
            for group in CER_group_list:
                assert len(str(group)) <= 4, f"Provincial group too long: {group}"
        elif aggregation == "individual":
            # Each generator should be its own group
            assert len(CER_group_list) == len(CER_generators)


@pytest.mark.unit
@pytest.mark.planning
def test_cer_generator_grouping_dispatch_mode(minimal_dispatch_network, cer_config):
    """Test CER generator grouping in dispatch mode"""
    network = minimal_dispatch_network
    # Set p_nom_opt for dispatch mode
    network.generators["p_nom_opt"] = network.generators["p_nom"] 
    period = 2030
    
    CER_generators, CER_group_budget, CER_group_list = CER_generator_grouping(
        network, cer_config, period, "dispatch"
    )
    
    # Dispatch mode uses p_nom_opt, not p_nom_max
    if not CER_generators.empty:
        assert all(CER_generators["p_nom_opt"] >= cer_config["min_cap"]), \
            "CER generators don't meet min_cap requirement"


# ============================================================================
# AGGREGATE GENERATORS INTO GROUP TESTS  
# ============================================================================

@pytest.mark.unit
@pytest.mark.planning
def test_aggregate_generators_provincial(minimal_planning_network, cer_config):
    """Test provincial aggregation of generators"""
    network = minimal_planning_network
    config = cer_config.copy()
    config["aggregation"] = "provincial"
    
    # Create test DataFrame
    gens = network.generators.copy()
    gens = gens[gens.carrier.isin(config["carriers"])]
    
    if not gens.empty:
        result = aggregate_generators_into_group(config, gens)
        assert "group" in result.columns
        # Provincial groups are first 2 chars of bus name
        for idx, row in result.iterrows():
            assert row["group"] == row["bus"][:2]


@pytest.mark.unit  
@pytest.mark.planning
def test_aggregate_generators_individual(minimal_planning_network, cer_config):
    """Test individual aggregation of generators"""
    network = minimal_planning_network
    config = cer_config.copy()
    config["aggregation"] = "individual"
    
    gens = network.generators.copy()
    gens = gens[gens.carrier.isin(config["carriers"])]
    
    if not gens.empty:
        result = aggregate_generators_into_group(config, gens)
        assert "group" in result.columns
        # Individual groups should be generator indices
        for idx, row in result.iterrows():
            assert row["group"] == idx
