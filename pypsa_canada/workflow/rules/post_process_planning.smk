
rule post_process_planning:
    input:
        solved_planning_network=f"{RUN_OUTPUT_DIR}/planning_solved_network"
    output:
        planning_postprocess=directory(f"{RUN_OUTPUT_DIR}/post_process_planning")
    log:
        f"{RUN_LOG_DIR}/post_process_planning_{TIMESTAMP}.log"
    script:
        "../scripts/post_process_planning.py"
