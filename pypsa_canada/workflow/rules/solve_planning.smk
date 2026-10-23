# Previous rule: modify_components
# Next rule: post_process_planning
rule solve_planning:
    input:
        unsolved_network=f"{RUN_NET_DIR}/base_network.nc"
    output:
        solved_network_csv=directory(f"{RUN_OUTPUT_DIR}/planning_solved_network")
    log:
        f"{RUN_LOG_DIR}/solve_planning_{TIMESTAMP}.log"
    script:
        "../scripts/solve_planning.py"
