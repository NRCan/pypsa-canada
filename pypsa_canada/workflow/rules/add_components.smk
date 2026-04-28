# Previous rule: load_network
# Next rule: add_snapshots
rule add_components:
    input:
        input_data=f"{RUN_NET_DIR}/load_network.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_components.nc"
    log:
       f"{RUN_LOG_DIR}/add_components.log"
    script:
        f"../scripts/add_components.py"
