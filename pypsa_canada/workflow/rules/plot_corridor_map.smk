# Previous rules: solve_planning, solve dispatch, post_process_planning, post_process_dispatch
# Next rule: None

_cm_timestamp = config.get("postprocess", {}).get("corridor_map", {}).get("timestamp") or TIMESTAMP

rule plot_corridor_map:
    input:
        planning_solved_network=f"{RUN_OUTPUT_DIR}/planning_solved_network",
        dispatch_solved_network=f"{RUN_OUTPUT_DIR}/dispatch_solved_network",
        post_process_planning=f"{RUN_OUTPUT_DIR}/post_process_planning",
        post_process_dispatch=f"{RUN_OUTPUT_DIR}/post_process_dispatch"
    output:
        planning_corridor_map=f"{RUN_OUTPUT_DIR}/planning_corridor_utilization_map.html",
        dispatch_corridor_map=f"{RUN_OUTPUT_DIR}/dispatch_corridor_utilization_map.html"
    log:
        f"{RUN_LOG_DIR}/plot_corridor_map_{_cm_timestamp}.log"
    script:
        "../scripts/plot_corridor_map.py"
