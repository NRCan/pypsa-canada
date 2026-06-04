workflow.scripts
=================

.. automodule:: pypsa_canada.workflow.scripts

Workflow scripts executed by Snakemake live in the |workflow_scripts| namespace.

This page is a documentation landing page only; the executable script modules
are not auto-imported during the Sphinx build because they rely on Snakemake
runtime globals and can execute side effects at import time.

.. rubric:: Helper modules

.. toctree::
   :maxdepth: 1

   pypsa_canada.workflow.scripts.load_load_forecast
   pypsa_canada.workflow.scripts.postprocess_helpers

.. rubric:: Executable scripts

add_components, add_extra_loads, add_loads, add_representative_days,
add_snapshots, create_dispatch_network, create_summary, export_idea,
load_network, modify_components, plot_corridor_map, post_process_dispatch,
post_process_planning, solve_dispatch, solve_planning.

