
rule create_planning_network:
    #input:
    #    config["input_file"]
    output:
        planning_unsolved_network_unfiltered=f"{RUN_NET_DIR}/planning_base_network.nc",
        planning_unsolved_network=f"{RUN_NET_DIR}/planning_unsolved_network.nc",
        # planning_unsolved_network_csv=directory("networks/unsolved/planning_base_network_csv")
        planning_unsolved_network_csv=directory(f"{RUN_NET_DIR}/planning_unsolved_network_csv")
        # solved_network_csv=directory(config["output_file"])
    log:
        f"{RUN_LOG_DIR}/create_planning_network.log"
    script:
        "../scripts/create_planning_network.py"