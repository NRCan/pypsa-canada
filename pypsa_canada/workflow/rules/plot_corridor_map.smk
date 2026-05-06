# Previous rule: solve_planning
# Next rule: None

_cm_cfg = config.get("corridor_map", {})
_cm_timestamp = _cm_cfg.get("timestamp", {TIMESTAMP}) 

rule plot_corridor_map:
    input:
        planning_solved_network=f"{RUN_RES_DIR}/planning_solved_network_{_cm_timestamp}",
        # dispatch_solved_network=f"{RUN_RES_DIR}/dispatch_solved_network_{TIMESTAMP}",
        post_process_planning=f"{RUN_RES_DIR}/post_process_planning_{_cm_timestamp}",
    output:
        corridor_map=f"{RUN_RES_DIR}/corridor_utilization_map_{_cm_timestamp}.html"
    log:
        f"{RUN_LOG_DIR}/plot_corridor_map_{_cm_timestamp}.log"
    script:
        "../scripts/plot_corridor_map.py"
