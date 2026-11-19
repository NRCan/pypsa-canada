# Previous rule: modify_components
# Next rule: solve_planning
rule add_representative_days:
    input:
        input_data=f"{RUN_NET_DIR}/base_network.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_representative_days.nc",
        planning_unsolved_network_unfiltered=f"{RUN_NET_DIR}/planning_unsolved_network.nc"
    log:
       f"{RUN_LOG_DIR}/add_representative_days.log"
    script:
        f"../scripts/add_representative_days.py"
