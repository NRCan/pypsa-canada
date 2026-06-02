# Previous rule: None
# Next rule: add_snapshots
rule add_loads:
    input:
        loads_p_set=f"{config["input_data"]}/loads-p_set.csv" if config["load"]["load_mode"].upper() == "GROWTH_FORECAST" else []
    output:
        loads_p_set=f"{RUN_NET_DIR}/add_loads.csv",
    log:
       f"{RUN_LOG_DIR}/add_loads.log"
    script:
        f"../scripts/add_loads.py"
