# Previous rule: None
# Next rule: add_components
rule load_network:
    input:
        input_data=config["input_data"]
    output:
        planning_unsolved_network=f"{RUN_NET_DIR}/load_network.nc"
    log:
       f"{RUN_LOG_DIR}/load_network.log"
    script:
        f"../scripts/load_network.py"
