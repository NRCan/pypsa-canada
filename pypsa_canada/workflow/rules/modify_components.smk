# Previous rule: add_extra_loads
# Next rule: solve_planning
rule modify_components:
    input:
        input_data=f"{RUN_NET_DIR}/add_extra_loads.nc"
    output:
        unsolved_network=f"{RUN_NET_DIR}/base_network.nc",
        unsolved_network_csv=directory(f"{RUN_NET_DIR}/base_network_csv")
    log:
       f"{RUN_LOG_DIR}/modify_components.log"
    script:
        f"../scripts/modify_components.py"
