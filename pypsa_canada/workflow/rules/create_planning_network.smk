
rule create_planning_network:
    #input:
    #    config["input_file"]
    output:
        planning_unsolved_network_unfiltered=config["planning_unsolved_network_unfiltered_nc"],
        planning_unsolved_network=config["planning_unsolved_network_nc"],
        # planning_unsolved_network_csv=directory("networks/unsolved/planning_base_network_csv")
        planning_unsolved_network_csv=directory(config["planning_unsolved_network_csv"])
        # solved_network_csv=directory(config["output_file"])
    log:
        "logs/create_planning_network.log"
    script:
        "../scripts/create_planning_network.py"