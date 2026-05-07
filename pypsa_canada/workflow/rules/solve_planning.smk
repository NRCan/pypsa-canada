# Previous rule: modify_components
# Next rule: create_dispatch_network
rule solve_planning:
    input:
        planning_unsolved_network=f"{RUN_NET_DIR}/planning_base_network.nc"
    output:
        solved_network_csv=directory(f"{RUN_OUTPUT_DIR}/planning_solved_network")
    log:
        f"{RUN_LOG_DIR}/solve_planning_{TIMESTAMP}.log"
    script:
        "../scripts/solve_planning.py"
