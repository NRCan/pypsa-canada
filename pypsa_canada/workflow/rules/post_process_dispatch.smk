
rule post_process_dispatch:
    input:
        solved_dispatch_network=f"{RUN_OUTPUT_DIR}/dispatch_solved_network"
    output:
        dispatch_postprocess=directory(f"{RUN_OUTPUT_DIR}/post_process_dispatch")
    log:
        f"{RUN_LOG_DIR}/post_process_dispatch_{TIMESTAMP}.log"
    script:
        "../scripts/post_process_dispatch.py"
