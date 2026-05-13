"""
Constraints module for PyPSA Canada model.

This module contains constraint functions for planning and dispatch optimization:
- Planning constraints: CER, reserve margin, emissions, capacity expansion
- Dispatch constraints: CER for dispatch, bidirectional links
- Generic constraints: Stop production, bidirectional links, spill prevention
"""

from .planning_constraints import (
    add_CER_constraint_planning,
    add_planning_reserve_margin,
    add_emission_constraint_planning,
    component_capacity_expansion_constraint,
)

from .dispatch_constraints import (
    distribute_CER_hours_dispatch,
    add_CER_constraint_dispatch,
)

from .generic_constraints import (
    CER_generator_grouping,
    aggregate_generators_into_group,
    add_spilling_variable,
    add_stop_prod_constraint,
    add_bidirection_link_constraint,
    prevent_spill_if_not_fully_charged,
)

__all__ = [
    # Planning constraints
    "add_CER_constraint_planning",
    "add_planning_reserve_margin",
    "add_emission_constraint_planning",
    "component_capacity_expansion_constraint",
    # Dispatch constraints
    "distribute_CER_hours_dispatch",
    "add_CER_constraint_dispatch",
    # Generic constraints
    "CER_generator_grouping",
    "aggregate_generators_into_group",
    "add_spilling_variable",
    "add_stop_prod_constraint",
    "add_bidirection_link_constraint",
    "prevent_spill_if_not_fully_charged",
]
