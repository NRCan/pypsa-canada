
rule compare_results:
    input:
        planning_dir=f"{RUN_OUTPUT_DIR}/post_process_planning",
        dispatch_dir=f"{RUN_OUTPUT_DIR}/post_process_dispatch"
    output:
        summary_output=f"{RUN_OUTPUT_DIR}/results_summary.csv"
    params:
        result_type=config.get('postprocess', {}).get('result_type', 'Provincial')
    log:
        f"{RUN_LOG_DIR}/create_summary_{TIMESTAMP}.log"
    script:
        "../scripts/create_summary.py"
