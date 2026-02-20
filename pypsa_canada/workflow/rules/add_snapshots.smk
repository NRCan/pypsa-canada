rule add_snapshots:
    input:
        input_data=f"{RUN_NET_DIR}/add_representative_days.nc",
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_snapshots.nc",
        planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/add_snapshots_csv"),
    log:
       f"{RUN_LOG_DIR}/add_snapshots.log"
    script:
        f"../scripts/add_snapshots.py"
