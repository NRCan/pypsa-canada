from snakemake.io import directory


rule all:
    input:
        config["output_file"]


rule solve_planning:
    input:
        config["input_file"]
    output:
        directory(config["output_file"])
    log:
        "logs/test.log",
    # benchmark:
    #     "benchmarks/" + RDIR + "clean_osm_data"
    script:
        "scripts/solve_planning.py"