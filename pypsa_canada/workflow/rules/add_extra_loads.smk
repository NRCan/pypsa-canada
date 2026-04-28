# Previous rule: add_representative_days
# Next rule: modify_components
rule add_extra_loads:
    input:
        input_data=f"{RUN_NET_DIR}/add_representative_days.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_extra_loads.nc"
    log:
       f"{RUN_LOG_DIR}/add_extra_loads.log"
    script:
        f"../scripts/add_extra_loads.py"
