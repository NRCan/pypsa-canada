# Previous rules: solve_planning, solve dispatch, post_process_planning, post_process_dispatch
# Next rule: None

rule plot_planning_corridor_map:
    input:
        planning_solved_network=f"{RUN_OUTPUT_DIR}/planning_solved_network",
        post_process_planning=f"{RUN_OUTPUT_DIR}/post_process_planning"
    output:
        planning_corridor_map=f"{RUN_OUTPUT_DIR}/post_process_maps/planning_corridor_utilization_map.html",
        planning_corridor_summary=f"{RUN_OUTPUT_DIR}/post_process_maps/planning_corridor_utilization_map_summary.csv"
    log:
        f"{RUN_LOG_DIR}/plot_planning_corridor_map_{TIMESTAMP}.log"
    script:
        "../scripts/plot_corridor_map.py"


rule plot_dispatch_corridor_map:
    input:
        planning_solved_network=f"{RUN_OUTPUT_DIR}/planning_solved_network",
        dispatch_solved_network=f"{RUN_OUTPUT_DIR}/dispatch_solved_network",
        post_process_planning=f"{RUN_OUTPUT_DIR}/post_process_planning",
        post_process_dispatch=f"{RUN_OUTPUT_DIR}/post_process_dispatch"
    output:
        dispatch_corridor_map=f"{RUN_OUTPUT_DIR}/post_process_maps/dispatch_corridor_utilization_map.html",
        dispatch_corridor_summary=f"{RUN_OUTPUT_DIR}/post_process_maps/dispatch_corridor_utilization_map_summary.csv"
    log:
        f"{RUN_LOG_DIR}/plot_dispatch_corridor_map_{TIMESTAMP}.log"
    script:
        "../scripts/plot_corridor_map.py"
