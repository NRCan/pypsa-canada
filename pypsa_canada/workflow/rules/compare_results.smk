
rule compare_results:
    input:
        planning_summary=f"{RUN_RES_DIR}/post_process_planning_{TIMESTAMP}/{config.get('postprocess', {{}}).get('result_type', 'Provincial')}_summary_planning.csv",
        dispatch_summary=f"{RUN_RES_DIR}/post_process_dispatch_{TIMESTAMP}/{config.get('postprocess', {{}}).get('result_type', 'Provincial')}_summary_dispatch.csv"
    output:
        compare_output=directory(f"{RUN_RES_DIR}/compare_results_{TIMESTAMP}")
    log:
        f"{RUN_LOG_DIR}/compare_results_{TIMESTAMP}.log"
    script:
        "../scripts/compare_results.py"
