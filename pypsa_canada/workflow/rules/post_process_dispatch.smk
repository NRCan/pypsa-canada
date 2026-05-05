
rule post_process_dispatch:
    input:
        solved_dispatch_network=f"{RUN_RES_DIR}/dispatch_solved_network_{TIMESTAMP}"
    output:
        dispatch_postprocess=directory(f"{RUN_RES_DIR}/post_process_dispatch_{TIMESTAMP}")
    log:
        f"{RUN_LOG_DIR}/post_process_dispatch_{TIMESTAMP}.log"
    script:
        "../scripts/post_process_dispatch.py"
