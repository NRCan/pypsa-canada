
rule solve_planning:
    input:
        planning_unsolved_network=f"{RUN_NET_DIR}/planning_base_network.nc"
    output:
        solved_network_csv=directory(config["planning_output_file_csv"])
    log:
        "logs/solve_planning.log"
    script:
        "../scripts/solve_planning.py"
