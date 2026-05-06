# Previous rule: solve_planning
# Next rule: None
rule plot_corridor_map:
    input:
        planning_solved_network=f"{RUN_RES_DIR}/planning_solved_network_{TIMESTAMP}",
        dispatch_solved_network=f"{RUN_RES_DIR}/dispatch_solved_network_{TIMESTAMP}"
    output:
        corridor_map=f"{RUN_RES_DIR}/corridor_utilization_map_{TIMESTAMP}.html"
    log:
        f"{RUN_LOG_DIR}/plot_corridor_map_{TIMESTAMP}.log"
    script:
        "../scripts/plot_corridor_map.py"
