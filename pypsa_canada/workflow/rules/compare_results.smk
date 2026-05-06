
rule compare_results:
    input:
        planning_dir=f"{RUN_OUTPUT_DIR}/post_process_planning",
        dispatch_dir=f"{RUN_OUTPUT_DIR}/post_process_dispatch"
    output:
        compare_output=directory(f"{RUN_OUTPUT_DIR}/compare_results")
    params:
        result_type=config.get('postprocess', {}).get('result_type', 'Provincial')
    log:
        f"{RUN_LOG_DIR}/compare_results_{TIMESTAMP}.log"
    script:
        "../scripts/compare_results.py"
