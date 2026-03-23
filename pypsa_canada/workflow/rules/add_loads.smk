# Previous rule: None
# Next rule: add_snapshots
rule add_loads:
    # input:
    output:
        loads_p_set=f"{RUN_NET_DIR}/add_loads.csv",
    log:
       f"{RUN_LOG_DIR}/add_loads.log"
    script:
        f"../scripts/add_loads.py"
