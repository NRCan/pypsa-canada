
rule add_components:
    input:
        input_data=f"{RUN_NET_DIR}/load_network.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_components.nc",
        planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/add_components_csv")
    log:
       f"{RUN_LOG_DIR}/add_components.log"
    script:
        f"../scripts/add_components.py"
