"""
Pytest-based tests for network pre-validation checks.

Run with: pytest tests/test_validation.py -v
"""

import numpy as np
import pypsa
import pytest
from common import CANADIAN_PROVINCES, validate_bus_provinces

# ============================================================================
# BUS PROVINCE VALIDATION TESTS
# ============================================================================


@pytest.mark.unit
def test_validate_bus_provinces_passes(minimal_planning_network):
    """Test that validation passes when all buses have valid province codes"""
    validate_bus_provinces(minimal_planning_network)


@pytest.mark.unit
def test_validate_bus_provinces_passes_dispatch(cer_dispatch_network):
    """Test that validation passes for dispatch network"""
    validate_bus_provinces(cer_dispatch_network)


@pytest.mark.unit
def test_validate_bus_provinces_missing_column():
    """Test that validation fails when province column is missing"""
    network = pypsa.Network()
    network.add("Bus", "test_bus", carrier="AC")

    with pytest.raises(ValueError, match="missing a 'province' column"):
        validate_bus_provinces(network)


@pytest.mark.unit
def test_validate_bus_provinces_invalid_code():
    """Test that validation fails for invalid province codes"""
    network = pypsa.Network()
    network.add("Bus", "test_bus", province="XX")

    with pytest.raises(ValueError, match="invalid province codes"):
        validate_bus_provinces(network)


@pytest.mark.unit
def test_validate_bus_provinces_nan_value():
    """Test that validation fails when a bus has a NaN province"""
    network = pypsa.Network()
    network.add("Bus", "bus_ok", province="AB")
    network.add("Bus", "bus_bad", province=np.nan)

    with pytest.raises(ValueError, match="missing a province value"):
        validate_bus_provinces(network)


@pytest.mark.unit
def test_canadian_provinces_complete():
    """Sanity check that the CANADIAN_PROVINCES set has all 13 provinces/territories"""
    assert len(CANADIAN_PROVINCES) == 13
