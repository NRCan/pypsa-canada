# Previous rules: post_process_planning, post_process_dispatch, compare_results
# Next rule: N/A

def get_log_inputs(wildcards=None):
    logs = [
        *rules.load_network.log,
        *rules.add_components.log,
        *rules.add_snapshots.log,
        *rules.add_representative_days.log,
        *rules.add_extra_loads.log,
        *rules.modify_components.log,
        *rules.solve_planning.log,
        *rules.create_dispatch_network.log,
        *rules.solve_dispatch.log,
        *rules.post_process_planning.log,
        *rules.post_process_dispatch.log,
        *rules.create_summary.log,
        *rules.copy_config.log,
        *rules.collect_logs.log
    ]
    if config["load"]["load_mode"].upper() != "DEFAULT": # Only add loads if not using default load profile, whose loads are already in the base network
        logs += [*rules.add_loads.log]
    if EXPORT_FORMAT and EXPORT_FORMAT.lower() == "idea":
        logs += [*rules.export_idea.log]
    return logs

rule copy_config:
    output:
        f"{RUN_OUTPUT_DIR}/config.yaml"
    run:
        with open(str(output[0]), "w") as f:
            yaml.dump(config, f, default_flow_style=False, allow_unicode=True)


rule collect_logs:
    input:
        get_log_inputs
    output:
        f"{RUN_OUTPUT_DIR}/run.log"
    run:
        with open(str(output[0]), encoding="utf-8", errors="replace", mode="w") as out_f:
            for log_file in input:
                header = f"{'='*60}\n## {log_file}\n{'='*60}\n"
                out_f.write(header)
                try:
                    with open(str(log_file), "r", encoding="utf-8", errors="replace") as in_f:
                        out_f.write(in_f.read())
                except FileNotFoundError:
                    out_f.write("[log file not found]\n")
                out_f.write("\n")


onerror:
    crash_dir = Path(RUN_RES_DIR) / f"crash_{TIMESTAMP}"
    run_output_dir = Path(RUN_OUTPUT_DIR)
    if run_output_dir.exists():
        run_output_dir.rename(crash_dir)
    # Remove the sentinel so the next invocation starts with a fresh timestamp.
    if _ts_file.exists():
        _ts_file.unlink()
    print(f"\n--- Crash detected: collecting artifacts to {crash_dir} ---")
    log_files = get_log_inputs()
    if EXPORT_FORMAT and EXPORT_FORMAT.lower() == "idea":
        log_files += [*rules.export_idea.log]
    collect_crash_artifacts(crash_dir, log_files, config, RUN_NET_DIR, RUN_START.timestamp())
    print(f"--- Crash artifacts saved to {crash_dir} ---\n")

onsuccess:
    # Remove the sentinel so the next invocation starts with a fresh timestamp.
    if _ts_file.exists():
        _ts_file.unlink()
