
rule solve_planning:
    input:
        planning_unsolved_network=f"{RUN_NET_DIR}/planning_base_network.nc"
    output:
        solved_network_csv=directory(f"{RUN_RES_DIR}/planning_solved_network_csv")
    log:
        f"{RUN_LOG_DIR}/solve_planning.log"
    script:
        "../scripts/solve_planning.py"
