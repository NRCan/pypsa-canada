
rule create_dispatch_network:
    input:
        planning_unsolved_network_unfiltered=f"{RUN_NET_DIR}/planning_base_network.nc",
        planning_solved_network=directory(f"{RUN_RES_DIR}/planning_solved_network_csv"),
    output:
        dispatch_planning_unsolved_network_nc=f"{RUN_NET_DIR}/dispatch_planning_unsolved_network.nc",
        dispatch_planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/dispatch_planning_unsolved_network_csv"),
    log:
        f"{RUN_LOG_DIR}/create_dispatch_network.log"
    script:
        "../scripts/create_dispatch_network.py"