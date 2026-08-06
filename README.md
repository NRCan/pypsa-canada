# PyPSA-Canada

**[English](#pypsa-canada)** | **[Français](#pypsa-canada-fr)**

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
(env)  >> pypsa_canada run -f config/[your-scenario].yaml
```

Available example scenarios in the `example/scenarios/` directory:
- `minimal_model.yaml`: Minimal network used for testing purposes

### Advanced Options
- **Unlock stale workflows**: If a previous run was interrupted, unlock with:
  ```bash
  pypsa_canada run -f scenarios/[scenario].yaml --unlock
  ```
- **View workflow graph**: Visualize the computational workflow (requires additional setup by installing graphviz)
    ```bash
  pypsa_canada dag -f scenarios/[scenario].yaml
  ```

### Data Organization
- `data/`: Input data including network components, costs, and constraints
- `config/`: YAML configuration files defining model scenarios
- `ressources/`: Intermediate network files generated during workflow
- `results/`: Optimization results and outputs

## Installation
Before starting the installation process:
0. Clone the following project/library pypsa_canada:
For GitHub users:
```bash
$ git clone https://github.com/NRCan/pypsa-canada.git
```

For NRCAN internal users:
```bash
$ git clone https://nrcan-eets-cev-renouvelable-devops@dev.azure.com/nrcan-eets-cev-renouvelable-devops/Canadian_Scenarios_Analysis/_git/pypsa_canada
```

1. Create the virtual environment with either Conda or Python with Python 3.12. Feel free to choose the name of your environment.

1-a) **For Anaconda/Miniconda users only, create a virtual environment with the following command:
```bash
$(base) conda create --name pypsa_canada_p312 python=3.12.10
```

1-b) **For Python users only, assuming you have a Python 3.12 installed, execute the following command to create a new virtual environment:
```bash
$(base) python -m venv pypsa_canada_p312
```

1-b) Proceed to activate the environment

2. Go into the project folder
```bash
(env)  >> cd [PROJECT_DIR]
```
3. Install the package/library:

```bash
(env)  >> pip install -e .[dev]
```

Following these steps, most dependencies should be installed and you should be able to use pypsa_canada

## Example (From the project folder)
1. Go into the project folder
```bash
(env)  >> cd [ROOT_DIR]/example
```

2. To execute an example
```bash
(env)  >> pypsa_canada run -f config\minimal_model.yaml
```

3. If the process is stale, you will need to unlock it with the following command
```bash
(env)  >> pypsa_canada run -f sconfig\minimal_model.yaml --unlock
```

## Developers
Pre-commit hooks are used within this project. The pre-commit hooks will be enforced through a pipeline during the pull request (PR). If it fails, the PR will be rejected. To validate if your changes are meeting the minimum standard, you should execute the following. If there are any issues, resolve them and commit again.
```bash
(pypsa-canada_py312)  >> pre-commit run --all-files --hook-stage manual
```

## Documentation
To build the documentation:
```bash
sphinx-build -b html docs/source docs/_build/html
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
* Adrien Prigent (adrien.prigent@nrcan-rncan.gc.ca)
* Serban Ivanescu (serban.ivanescu@nrcan-rncan.gc.ca)

## Getting Further Information
https://docs.pypsa.org/latest/

---

<a name="pypsa-canada-fr"></a>
# PyPSA-Canada

**[English](#pypsa-canada)** | **[Français](#pypsa-canada-fr)**

## Mots-clés
Python, Optimisation, Linopy, Réseaux électriques

## Description du projet
`pypsa_canada` est un cadre de modélisation basé sur des flux de travail pour l'analyse des réseaux électriques au Canada, construit sur [PyPSA](https://pypsa.org/) (Python for Power System Analysis). Cet outil permet une optimisation et une planification complètes des systèmes énergétiques pour les réseaux électriques canadiens.

**Caractéristiques principales :**
- **Modélisation par scénarios** : Définir et exécuter plusieurs scénarios de réseaux électriques avec des configurations personnalisables
- **Analyse multi-temporelle** : Support pour la planification à long terme et la modélisation de la répartition opérationnelle
- **Jours représentatifs** : Modélisation efficace utilisant des périodes de temps représentatives pour réduire la complexité computationnelle
- **Modélisation flexible du réseau** : Modéliser les réseaux électriques à différentes échelles spatiales (nationale, provinciale, régionale)
- **Intégration des composants** : Gérer divers composants du système énergétique, y compris les générateurs, les unités de stockage, les charges et les liens de transmission
- **Optimisation des coûts** : Incorporer des données détaillées sur les coûts en capital, opérationnels et de carburant avec plusieurs scénarios de coûts
- **Gestion des contraintes** : Appliquer des contraintes personnalisées, y compris les limites de capacité, les objectifs d'émissions et les exigences politiques
- **Automatisation du flux de travail** : Pipeline basé sur Snakemake pour une analyse reproductible et évolutive

Ce cadre a été appliqué pour analyser des scénarios de réseaux électriques canadiens, y compris l'initiative de la Boucle de l'Atlantique et l'intégration du réseau de la Saskatchewan.

## Utilisation

### Aperçu
`pypsa_canada` fournit une interface en ligne de commande pour exécuter des flux de travail d'optimisation de réseaux électriques. L'outil traite les fichiers de configuration de scénarios (YAML) et exécute une série de tâches automatisées, y compris la création de réseaux, le chargement de données, l'application de contraintes et la résolution d'optimisation.

### Flux de travail de base
Le flux de travail typique comprend :
1. **Préparer les données d'entrée** : Composants du réseau (bus, générateurs, charges, etc.), données de coûts et contraintes
2. **Définir le scénario** : Créer un fichier de configuration YAML spécifiant les paramètres et hypothèses du modèle
3. **Exécuter l'optimisation** : Exécuter le flux de travail en utilisant l'interface en ligne de commande
4. **Analyser les résultats** : Examiner les sorties, y compris la répartition optimale, l'expansion de la capacité et les coûts du système

### Interface en ligne de commande
Exécuter un scénario avec :
```bash
(env)  >> pypsa_canada run -f config/[votre-scenario].yaml
```

Scénarios d'exemple disponibles dans le répertoire `example/scenarios/` :
- `minimal_model.yaml` : Réseau minimal utilisé à des fins de test

### Options avancées
- **Déverrouiller les flux de travail bloqués** : Si une exécution précédente a été interrompue, déverrouillez avec :
  ```bash
  pypsa_canada run -f scenarios/[scenario].yaml --unlock
  ```
- **Visualiser le graphique du flux de travail** : Visualiser le flux de travail computationnel (nécessite une configuration supplémentaire en installant graphviz)
    ```bash
  pypsa_canada dag -f scenarios/[scenario].yaml
  ```

### Organisation des données
- `data/` : Données d'entrée, y compris les composants du réseau, les coûts et les contraintes
- `config/` : Fichiers de configuration YAML définissant les scénarios du modèle
- `ressources/` : Fichiers de réseau intermédiaires générés pendant le flux de travail
- `results/` : Résultats et sorties d'optimisation

## Installation
Avant de commencer le processus d'installation :
0. Clonez le projet/bibliothèque pypsa_canada suivant :
Pour les utilisateurs de GitHub :
```bash
$ git clone https://github.com/NRCan/pypsa-canada.git
```

Pour les utilisateurs internes de RNCan :
```bash
$ git clone https://nrcan-eets-cev-renouvelable-devops@dev.azure.com/nrcan-eets-cev-renouvelable-devops/Canadian_Scenarios_Analysis/_git/pypsa_canada
```

1. Créez l'environnement virtuel avec Conda ou Python avec Python 3.12. N'hésitez pas à choisir le nom de votre environnement.

1-a) **Pour les utilisateurs d'Anaconda/Miniconda uniquement, créez un environnement virtuel avec la commande suivante :
```bash
$(base) conda create --name pypsa_canada_p312 python=3.12.10
```

1-b) **Pour les utilisateurs de Python uniquement, en supposant que vous avez Python 3.12 installé, exécutez la commande suivante pour créer un nouvel environnement virtuel :
```bash
$(base) python -m venv pypsa_canada_p312
```

1-b) Procédez à l'activation de l'environnement

2. Allez dans le dossier du projet
```bash
(env)  >> cd [PROJECT_DIR]
```
3. Installez le package/bibliothèque :

```bash
(env)  >> pip install -e .[dev]
```

Après ces étapes, la plupart des dépendances devraient être installées et vous devriez pouvoir utiliser pypsa_canada

## Exemple (À partir du dossier du projet)
1. Allez dans le dossier du projet
```bash
(env)  >> cd [ROOT_DIR]/example
```

2. Pour exécuter un exemple
```bash
(env)  >> pypsa_canada run -f config\minimal_model.yaml
```

3. Si le processus est bloqué, vous devrez le déverrouiller avec la commande suivante
```bash
(env)  >> pypsa_canada run -f sconfig\minimal_model.yaml --unlock
```

## Développeurs
Des hooks de pré-commit sont utilisés dans ce projet. Les hooks de pré-commit seront appliqués via un pipeline pendant la demande de tirage (PR). S'il échoue, la PR sera rejetée. Pour valider si vos modifications répondent au standard minimum, vous devez exécuter ce qui suit. S'il y a des problèmes, résolvez-les et validez à nouveau.
```bash
(pypsa-canada_py312)  >> pre-commit run --all-files --hook-stage manual
```

## Documentation
Pour construire la documentation :
```bash
sphinx-build -b html docs/source docs/_build/html
```

## Licence
Licence MIT PyPSA : https://github.com/PyPSA/PyPSA/blob/master/LICENSE.txt
Licence pypsa-eur : https://github.com/PyPSA/pypsa-eur/tree/master/LICENSES

## Droits
Copyright CanmetÉNERGIE - Varennes, RNCan, Gouvernement du Canada

## Auteurs
* Steven Wong (Ressources naturelles Canada - CanmetÉNERGIE)
* Nathan De Matos (Ressources naturelles Canada - CanmetÉNERGIE)
* Michel Bui (Ressources naturelles Canada - CanmetÉNERGIE)
* Sophie Pelland (Ressources naturelles Canada - CanmetÉNERGIE)
* Matheus Zambroni De Souza (Ressources naturelles Canada - CanmetÉNERGIE)
* Adrien Prigent (Ressources naturelles Canada - CanmetÉNERGIE)
* Serban Ivanescu (Ressources naturelles Canada - CanmetÉNERGIE)

## Coordonnées
* Steven Wong (steven.wong@nrcan-rncan.gc.ca)
* Nathan De Matos (nathan.dematos@nrcan-rncan.gc.ca)
* Michel Bui (michel.bui@nrcan-rncan.gc.ca)
* Sophie Pelland (sophie.pelland@nrcan-rncan.gc.ca)
* Adrien Prigent (adrien.prigent@nrcan-rncan.gc.ca)
* Serban Ivanescu (serban.ivanescu@nrcan-rncan.gc.ca)

## Pour plus d'informations
https://docs.pypsa.org/latest/
