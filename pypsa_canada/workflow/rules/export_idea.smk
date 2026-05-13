
rule export_idea:
    input:
        planning_dir=f"{RUN_OUTPUT_DIR}/post_process_planning",
        dispatch_dir=f"{RUN_OUTPUT_DIR}/post_process_dispatch"
    output:
        idea_output=f"{RUN_OUTPUT_DIR}/idea_outputs.csv"
    params:
        result_type=config.get('postprocess', {}).get('result_type', 'Provincial')
    log:
        f"{RUN_LOG_DIR}/export_idea_{TIMESTAMP}.log"
    script:
        "../scripts/export_idea.py"
