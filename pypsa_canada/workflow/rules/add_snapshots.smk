# Previous rules: add_loads, add_representative_days
# Next rule: modify_components
rule add_snapshots:
    input:
        input_data=f"{RUN_NET_DIR}/add_representative_days.nc",
        loads_p_set=f"{RUN_NET_DIR}/add_loads.csv"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_snapshots.nc"
    log:
       f"{RUN_LOG_DIR}/add_snapshots.log"
    script:
        f"../scripts/add_snapshots.py"
