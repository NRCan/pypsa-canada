
rule solve_dispatch:
    input:
        unsolved_dispatch_network=config["dispatch_unsolved_network_csv"]
    output:
        dispatch_output_file_csv=directory(config["dispatch_output_file_csv"]),
        #solved_dispatch_network_nc=config["dispatch_output_file_nc"]
    log:
        "logs/solve_dispatch.log"
    script:
        "../scripts/solve_dispatch.py"