# Previous rule: modify_components
# Next rule: solve_dispatch
rule create_dispatch_network:
    input:
        base_network=f"{RUN_NET_DIR}/base_network.nc",
        planning_solved_network=directory(f"{RUN_OUTPUT_DIR}/planning_solved_network") if "planning" in WORKFLOW_STAGES else [],
    output:
        dispatch_planning_unsolved_network_nc=f"{RUN_NET_DIR}/dispatch_planning_unsolved_network.nc",
        dispatch_planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/dispatch_planning_unsolved_network_csv"),
    log:
        f"{RUN_LOG_DIR}/create_dispatch_network.log"
    script:
        "../scripts/create_dispatch_network.py"