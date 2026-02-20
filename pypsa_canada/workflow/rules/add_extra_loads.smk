
# OUT_DIR = f"networks/{config["run"]["name"]}"
# LOG_DIR = f"logs/{config["run"]["name"]}"
rule add_extra_loads:
    input:
        input_data=f"{RUN_NET_DIR}/add_snapshots.nc"
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/add_extra_loads.nc",
        planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/add_extra_loads_csv")
    log:
       f"{RUN_LOG_DIR}/add_extra_loads.log"
    script:
        f"../scripts/add_extra_loads.py"
