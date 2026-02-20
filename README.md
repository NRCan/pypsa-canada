# PyPSA

## Keywords
Python, Optimization, Linopy, Power Systems

## Project Description
`pypsa_canada` is a workflow-based modeling framework for power system analysis in Canada, built on top of [PyPSA](https://pypsa.org/) (Python for Power System Analysis). This tool enables comprehensive energy system optimization and planning for Canadian electricity grids.

**Key Features:**
- **Scenario-based modeling**: Define and run multiple power system scenarios with customizable configurations
- **Multi-temporal analysis**: Support for both long-term planning and operational dispatch modeling
- **Representative days**: Efficient modeling using representative time periods to reduce computational complexity
- **Flexible network modeling**: Model power systems at various spatial scales (national, provincial, regional)
- **Component integration**: Handle diverse energy system components including generators, storage units, loads, and transmission links
- **Cost optimization**: Incorporate detailed capital, operational, and fuel cost data with multiple cost scenarios
- **Constraint management**: Apply custom constraints including capacity limits, emission targets, and policy requirements
- **Workflow automation**: Snakemake-based pipeline for reproducible and scalable analysis

This framework has been applied to analyze Canadian power system scenarios including the Atlantic Loop initiative and Saskatchewan grid integration.

## Usage

### Overview
`pypsa_canada` provides a command-line interface to run power system optimization workflows. The tool processes scenario configuration files (YAML) and executes a series of automated tasks including network creation, data loading, constraint application, and optimization solving.

### Basic Workflow
The typical workflow involves:
1. **Prepare input data**: Network components (buses, generators, loads, etc.), cost data, and constraints
2. **Define scenario**: Create a YAML configuration file specifying model parameters and assumptions
3. **Run optimization**: Execute the workflow using the CLI
4. **Analyze results**: Review outputs including optimal dispatch, capacity expansion, and system costs

### Command-Line Interface
Run a scenario with:
```bash
pypsa_canada run -f scenarios/[your-scenario].yaml
```

Available example scenarios in the `example/scenarios/` directory:
- `Canada-National-no-CER.yaml`: National-scale Canadian grid without specific regulations
- `tutorial_config.yaml`: Tutorial configuration for learning the framework
- `constraint_testing.yaml`: Testing custom constraint implementations

### Advanced Options
- **Unlock stale workflows**: If a previous run was interrupted, unlock with:
  ```bash
  pypsa_canada run -f scenarios/[scenario].yaml --unlock
  ```
- **View workflow graph**: Visualize the computational workflow (requires additional setup)
- **Dry run**: Preview workflow steps without execution

### Data Organization
- `data/`: Input data including network components, costs, and constraints
- `scenarios/`: YAML configuration files defining model scenarios
- `networks/`: Intermediate network files generated during workflow
- `results/`: Optimization results and outputs

## Installation
Before starting the installation process:
0. Clone the following project/library pypsa_canada:
```bash
$ git clone https://nrcan-eets-cev-renouvelable-devops@dev.azure.com/nrcan-eets-cev-renouvelable-devops/Canadian_Scenarios_Analysis/_git/pypsa_canada
```

1. Create the virtual environment with either Conda or Python with Python 3.11

1-a) **For Anaconda/Miniconda users only, create a virtual environment with the following command:
```bash
$(base) conda create --name pypsa_cad_p312 python=3.12.10
```

1-b) **For Python users only, assuming you have a Python 3.12 installed, execute the following command to create a new virtual environment:
```bash
$(base) python -m venv pypsa_cad_p312
```
1-b) Proceed to activate the environment

2. Go into the project folder
```bash
(env)  >> cd [PROJECT_DIR]
```
3. Install the package/library:

a) For developpers:
```bash
(pypsa-cad_py312)  >> pip install -e .[dev]
```
b) For users:
```bash
(pypsa-cad_py312)  >> pip install git+https://nrcan-eets-cev-renouvelable-devops@dev.azure.com/nrcan-eets-cev-renouvelable-devops/Canadian_Scenarios_Analysis/_git/pypsa_cad
```

Following these steps, most dependencies should be installed and you should be able to use pypsa_canada

## Example (From the project folder)
1. Clone the following project [pypsa-canada] (https://nrcan-eets-cev-renouvelable-devops@dev.azure.com/nrcan-eets-cev-renouvelable-devops/Canadian_Scenarios_Analysis/_git/pypsa_canada)

2. Go into the project folder
```bash
(env)  >> cd [ROOT_DIR]/example
```

3. To execute an example
```bash
(pypsa-cad_py312)  >> pypsa_canada run -f scenarios\Canada-National-no-CER.yaml
```

4. If the process is stale, you will need to unlock it with the following command
```bash
(pypsa-cad_py312)  >> pypsa_canada run -f scenarios\Canada-National-no-CER.yaml --unlock
```

## Developpers
Pre-commit hooks are used within this project. The pre-commit hooks will be enforced through a pipeline during the pull request (PR). If it fails, the PR will be rejected. To validate if your changes are meeting the minimum standard, you should execute the following. If there are any issues, resolve them and commit again.
```bash
(pypsa-canada_py312)  >> pre-commit run --all-files --hook-stage manual
```

## Licence
PyPSA MIT License : https://github.com/PyPSA/PyPSA/blob/master/LICENSE.txt
pypsa-eur License: https://github.com/PyPSA/pypsa-eur/tree/master/LICENSES

## Rights
Copyright CanmetENERGY - Varennes, NRCan, Goverment of Canada

## Authors
* Steven Wong (Natural Resources Canada - CanmetENERGY)
* Nathan De Matos (Natural Resources Canada - CanmetENERGY)
* Michel Bui (Natural Resources Canada - CanmetENERGY)
* Sophie Pelland (Natural Resources Canada - CanmetENERGY)
* Matheus Zambroni De Souza (Natural Resources Canada - CanmetENERGY)
* Adrien Prigent (Natural Resources Canada - CanmetENERGY)
* Serban Ivanescu (Natural Resources Canada - CanmetENERGY)

## Contact Information
* Steven Wong (steven.wong@nrcan-rncan.gc.ca)
* Nathan De Matos (nathan.dematos@nrcan-rncan.gc.ca)
* Michel Bui (michel.bui@nrcan-rncan.gc.ca)
* Sophie Pelland (sophie.pelland@nrcan-rncan.gc.ca)
* Matheus Zambroni De Souza (matheus.zambronidesouza@nrcan-rncan.gc.ca)
* Adrien Prigent (adrien.prigent@nrcan-rncan.gc.ca)
* Serban Ivanescu (serban.ivanescu@nrcan-rncan.gc.ca)

## Getting Further Information
https://pypsa.readthedocs.io/en/latest/index.html
