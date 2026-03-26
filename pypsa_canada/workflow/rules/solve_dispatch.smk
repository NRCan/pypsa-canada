
rule solve_dispatch:
    input:
        unsolved_dispatch_network=f"{RUN_NET_DIR}/dispatch_planning_unsolved_network.nc",
    output:
        dispatch_output_file_csv=directory(f"{RUN_RES_DIR}/dispatch_solved_network_csv"),
        #solved_dispatch_network_nc=config["dispatch_output_file_nc"]
    log:
        f"{RUN_LOG_DIR}/solve_dispatch.log"
    script:
        "../scripts/solve_dispatch.py"