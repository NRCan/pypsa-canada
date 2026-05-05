
rule post_process_planning:
    input:
        solved_planning_network=f"{RUN_RES_DIR}/planning_solved_network_{TIMESTAMP}"
    output:
        planning_postprocess=directory(f"{RUN_RES_DIR}/post_process_planning_{TIMESTAMP}")
    log:
        f"{RUN_LOG_DIR}/post_process_planning_{TIMESTAMP}.log"
    script:
        "../scripts/post_process_planning.py"
