# Previous rule: add_components
# Next rule: add_snapshots
rule add_representative_days:
    input:
        input_data=f"{RUN_NET_DIR}/add_components.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_representative_days.nc",
        planning_unsolved_network_unfiltered=f"{RUN_NET_DIR}/planning_unsolved_network.nc",
        snapshot_status=f"{RUN_NET_DIR}/snapshot_status"
    log:
       f"{RUN_LOG_DIR}/add_representative_days.log"
    script:
        f"../scripts/add_representative_days.py"
