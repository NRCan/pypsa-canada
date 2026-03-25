
rule create_dispatch_network:
    input:
        planning_unsolved_network_unfiltered=f"{RUN_NET_DIR}/planning_base_network.nc",
        planning_solved_network=config["planning_output_file_csv"]
    output:
        dispatch_planning_unsolved_network_nc=config["dispatch_unsolved_network_nc"],
        dispatch_planning_unsolved_network_csv=directory(config["dispatch_unsolved_network_csv"])
    log:
        "logs/create_dispatch_network.log"
    script:
        "../scripts/create_dispatch_network.py"