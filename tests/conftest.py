"""
Pytest fixtures for constraint testing

Provides reusable network fixtures and configuration for testing PyPSA constraints.
"""

import os
import sys
from pathlib import Path

import pytest
import pypsa
import pandas as pd

# Add the scripts directory to path to import constraints
sys.path.insert(0, str(Path(__file__).parent.parent / "pypsa_canada" / "workflow" / "scripts"))


@pytest.fixture(scope="session")
def data_folder():
    """Path to the test data folder - points to tests directory"""
    return Path(__file__).parent / "data"


@pytest.fixture(autouse=True)
def setup_data_folder(data_folder):
    """Automatically set up custom data folder for all tests"""
    os.environ['PYPSA_CUSTOM_DATA_FOLDER'] = str(data_folder.resolve())
    yield
    # Cleanup after test
    if 'PYPSA_CUSTOM_DATA_FOLDER' in os.environ:
        del os.environ['PYPSA_CUSTOM_DATA_FOLDER']


@pytest.fixture
def minimal_planning_network():
    """Create a minimal planning network for testing"""
    network = pypsa.Network()
    network.set_investment_periods([2025, 2030, 2035, 2040])
    
    # Create multi-period snapshots
    snapshots = pd.DatetimeIndex([])
    for year in network.investment_periods:
        year_snapshots = pd.date_range(f"{year}-01-01", periods=24, freq="h")
        snapshots = snapshots.append(year_snapshots)
    
    network.set_snapshots(pd.MultiIndex.from_arrays(
        [snapshots.year, snapshots],
        names=["period", "timestep"]
    ))
    
    # Add minimal components
    network.add("Bus", "test_bus", carrier="AC")
    
    network.add("Generator", "test_gen_gas",
                bus="test_bus",
                p_nom=100,
                carrier="gas_CC",
                marginal_cost=50,
                efficiency=0.6,
                p_nom_extendable=True,
                committable=True,
                build_year=2020,
                lifetime=30)
    
    network.add("Generator", "test_gen_wind",
                bus="test_bus",
                p_nom=50,
                carrier="wind_new",
                marginal_cost=0,
                p_nom_extendable=True,
                build_year=2020,
                lifetime=25)
    
    network.add("Load", "test_load",
                bus="test_bus",
                p_set=80)
    
    # Add carriers with emissions
    network.add("Carrier", "gas_CC", co2_emissions=0.2)
    network.add("Carrier", "wind_new", co2_emissions=0.0)
    
    # Add model attribute (required for some constraints)
    network.generators["model"] = network.generators["carrier"]
    
    return network


@pytest.fixture
def minimal_dispatch_network():
    """Create a minimal dispatch network for testing"""
    network = pypsa.Network()
    snapshots = pd.date_range("2030-01-01", periods=168, freq="h")  # 1 week
    network.set_snapshots(snapshots)
    
    # Add minimal components
    network.add("Bus", "test_bus", carrier="AC")
    
    network.add("Generator", "test_gen_gas",
                bus="test_bus",
                p_nom=100,
                carrier="gas_CC",
                marginal_cost=50,
                efficiency=0.6,
                p_nom_extendable=False,
                committable=True,
                build_year=2020,
                lifetime=30)
    
    network.add("Generator", "test_gen_wind",
                bus="test_bus",
                p_nom=50,
                carrier="wind_new",
                marginal_cost=0,
                p_nom_extendable=False,
                build_year=2020,
                lifetime=25)
    
    network.add("Load", "test_load",
                bus="test_bus",
                p_set=80)
    
    # Add carriers with emissions
    network.add("Carrier", "gas_CC", co2_emissions=0.2)
    network.add("Carrier", "wind_new", co2_emissions=0.0)
    
    return network


@pytest.fixture
def network_with_storage(minimal_planning_network):
    """Add storage unit with inflow to planning network"""
    network = minimal_planning_network
    network.add("StorageUnit", "test_hydro",
                bus="test_bus",
                p_nom=100,
                max_hours=10,
                carrier="hydro",
                p_nom_extendable=False)
    network.storage_units_t.inflow = pd.DataFrame(
        10.0, index=network.snapshots, columns=["test_hydro"]
    )
    return network


@pytest.fixture
def network_with_links(minimal_planning_network):
    """Add bidirectional links to planning network"""
    network = minimal_planning_network
    network.add("Bus", "test_bus_2", carrier="AC")
    network.add("Link", "link_forward",
                bus0="test_bus",
                bus1="test_bus_2",
                p_nom=50,
                p_nom_extendable=True)
    network.add("Link", "link_reverse",
                bus0="test_bus_2",
                bus1="test_bus",
                p_nom=50,
                p_nom_extendable=True)
    return network


@pytest.fixture
def cer_config():
    """Default CER constraint configuration"""
    return {
        "year": 2035,
        "carriers": ["gas_CC"],
        "aggregation": "provincial",
        "values": {
            "limit": {2035: 30},
            "offset": {2035: 0}
        },
        "min_cap": 25
    }


@pytest.fixture
def reserve_margin_config():
    """Default reserve margin configuration"""
    return {
        "province": "test",
        "margin": 1.2,
        "period": 2030
    }


@pytest.fixture
def emissions_config():
    """Default emissions constraint configuration"""
    return {
        "period": 2030,
        "limit": 100  # MtCO2eq
    }
