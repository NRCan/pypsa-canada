# SPDX-FileCopyrightText: Contributors to PyPSA-Eur <https://github.com/pypsa/pypsa-eur>
#
# SPDX-License-Identifier: MIT


import logging
import csv
import inspect
import os
import signal
import sys
import time
from datetime import timedelta
from pathlib import Path

try:
    from memory_profiler import _get_memory, choose_backend
except ImportError:  # pragma: no cover - optional dependency for memory logging only
    _get_memory = None
    choose_backend = None

logger = logging.getLogger(__name__)

BENCHMARK_COLUMNS = [
    "rule_name",
    "elapsed_seconds",
    "h:m:s",
    "max_memory",
    "memory_measurements",
]

BENCHMARK_RESULTS_FILENAME = "results_benchmarks.csv"

# TODO: provide alternative when multiprocessing is not available
try:
    from multiprocessing import Pipe, Process
except ImportError:
    from multiprocessing.dummy import Pipe, Process


# The memory logging facilities have been adapted from memory_profiler
class MemTimer(Process):
    """
    Write memory consumption over a time interval to file until signaled to
    stop on the pipe.
    """

    def __init__(
        self, monitor_pid, interval, pipe, filename, max_usage, backend, *args, **kw
    ):
        self.monitor_pid = monitor_pid
        self.interval = interval
        self.pipe = pipe
        self.filename = filename
        self.max_usage = max_usage
        self.backend = backend

        self.timestamps = kw.pop("timestamps", True)
        self.include_children = kw.pop("include_children", True)

        super().__init__(*args, **kw)

    def run(self):
        # ignore the interrupt signal in the child process
        signal.signal(signal.SIGINT, signal.SIG_IGN)

        # get baseline memory usage
        cur_mem = _get_memory(
            self.monitor_pid,
            self.backend,
            timestamps=self.timestamps,
            include_children=self.include_children,
        )

        n_measurements = 1
        mem_usage = cur_mem if self.max_usage else [cur_mem]

        if self.filename is not None:
            stream = open(self.filename, "w")
            stream.write("MEM {:.6f} {:.4f}\n".format(*cur_mem))
            stream.flush()
        else:
            stream = None

        self.pipe.send(0)  # we're ready
        stop = False
        while True:
            cur_mem = _get_memory(
                self.monitor_pid,
                self.backend,
                timestamps=self.timestamps,
                include_children=self.include_children,
            )

            if stream is not None:
                stream.write("MEM {:.6f} {:.4f}\n".format(*cur_mem))
                stream.flush()

            n_measurements += 1
            if not self.max_usage:
                mem_usage.append(cur_mem)
            else:
                mem_usage = max(cur_mem, mem_usage)

            if stop:
                break
            stop = self.pipe.poll(self.interval)
            # do one more iteration

        if stream is not None:
            stream.close()

        self.pipe.send(mem_usage)
        self.pipe.send(n_measurements)


class memory_logger:
    """
    Context manager for taking and reporting memory measurements at fixed
    intervals from a separate process, for the duration of a context.

    Parameters
    ----------
    filename : None|str
        Name of the text file to log memory measurements, if None no log is
        created (defaults to None)
    interval : float
        Interval between measurements (defaults to 1.)
    max_usage : bool
        If True, only store and report the maximum value (defaults to True)
    timestamps : bool
        Whether to record tuples of memory usage and timestamps; if logging to
        a file timestamps are always kept (defaults to True)
    include_children : bool
        Whether the memory of subprocesses is to be included (default: True)

    Arguments
    ---------
    n_measurements : int
        Number of measurements that have been taken
    mem_usage : (float, float)|[(float, float)]
        All memory measurements and timestamps (if timestamps was True) or only
        the maximum memory usage and its timestamp

    Note
    ----
    The arguments are only set after all the measurements, i.e. outside of the
    with statement.

    Example
    -------
    with memory_logger(filename="memory.log", max_usage=True) as mem:
        # Do a lot of long running memory intensive stuff
        hard_memory_bound_stuff()

    max_mem, timestamp = mem.mem_usage
    """

    def __init__(
        self,
        filename=None,
        interval=1.0,
        max_usage=True,
        timestamps=True,
        include_children=True,
    ):
        if filename is not None:
            timestamps = True

        self.filename = filename
        self.interval = interval
        self.max_usage = max_usage
        self.timestamps = timestamps
        self.include_children = include_children

    def __enter__(self):
        backend = choose_backend()

        self.child_conn, self.parent_conn = Pipe()  # this will store MemTimer's results
        self.p = MemTimer(
            os.getpid(),
            self.interval,
            self.child_conn,
            self.filename,
            backend=backend,
            timestamps=self.timestamps,
            max_usage=self.max_usage,
            include_children=self.include_children,
        )
        self.p.start()
        self.parent_conn.recv()  # wait until memory logging in subprocess is ready

        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is None:
            self.parent_conn.send(0)  # finish timing

            self.mem_usage = self.parent_conn.recv()
            self.n_measurements = self.parent_conn.recv()
        else:
            self.p.terminate()

        return False


class timer:
    level = 0
    opened = False

    def __init__(self, name="", verbose=True):
        self.name = name
        self.verbose = verbose

    def __enter__(self):
        if self.verbose:
            if self.opened:
                sys.stdout.write("\n")

            if len(self.name) > 0:
                sys.stdout.write((".. " * self.level) + self.name + ": ")
            sys.stdout.flush()

            self.__class__.opened = True

        self.__class__.level += 1

        self.start = time.time()
        return self

    def print_usec(self, usec):
        if usec < 1000:
            print(f"{usec:.1f} usec")
        else:
            msec = usec / 1000
            if msec < 1000:
                print(f"{msec:.1f} msec")
            else:
                sec = msec / 1000
                print(f"{sec:.1f} sec")

    def __exit__(self, exc_type, exc_val, exc_tb):
        if not self.opened and self.verbose:
            sys.stdout.write(".. " * self.level)

        if exc_type is None:
            stop = time.time()
            self.usec = usec = (stop - self.start) * 1e6
            if self.verbose:
                self.print_usec(usec)
        elif self.verbose:
            print("failed")
        sys.stdout.flush()

        self.__class__.level -= 1
        if self.verbose:
            self.__class__.opened = False
        return False


def write_benchmark_file(path, elapsed_seconds: float) -> Path:
    """Write a simple benchmark report to path and return the path."""
    benchmark_path = Path(path)
    benchmark_path.parent.mkdir(parents=True, exist_ok=True)
    benchmark_path.write_text(
        "elapsed_seconds\th:m:s\n"
        f"{elapsed_seconds:.4f}\t{timedelta(seconds=elapsed_seconds)}\n",
        encoding="utf-8",
    )
    return benchmark_path


def result_benchmark_csv_path(output_path) -> Path | None:
    """Return the consolidated CSV path next to a rule output directory."""
    caller_frame = inspect.currentframe().f_back if inspect.currentframe() else None
    if caller_frame is not None:
        caller_snakemake = caller_frame.f_globals.get("snakemake")
        caller_config = getattr(caller_snakemake, "config", None)
        if caller_config:
            configured_path = caller_config.get("run", {}).get("benchmark_results_file")
            if configured_path:
                return Path(configured_path)

    if not output_path:
        return None
    output_path = Path(output_path)
    if output_path.suffix:
        return output_path.parent / BENCHMARK_RESULTS_FILENAME
    return output_path / BENCHMARK_RESULTS_FILENAME


def append_benchmark_row(result_path, row: dict[str, object]) -> Path:
    """Append one row to a CSV file, creating it if needed."""
    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    normalized_row = {
        column: str(row.get(column, "NA")) for column in BENCHMARK_COLUMNS
    }
    extra_columns = [key for key in row.keys() if key not in BENCHMARK_COLUMNS]
    for column in extra_columns:
        normalized_row[column] = str(row[column])

    existing_rows: list[dict[str, str]] = []
    existing_fields: list[str] = []

    if result_path.exists():
        with result_path.open("r", encoding="utf-8", newline="") as result_stream:
            reader = csv.DictReader(result_stream)
            existing_fields = list(reader.fieldnames or [])
            existing_rows = [dict(existing_row) for existing_row in reader]

    merged_fields: list[str] = []
    for field in BENCHMARK_COLUMNS + existing_fields + list(normalized_row.keys()):
        if field and field not in merged_fields:
            merged_fields.append(field)

    with result_path.open("w", encoding="utf-8", newline="") as result_stream:
        writer = csv.DictWriter(result_stream, fieldnames=merged_fields)
        writer.writeheader()
        for existing_row in existing_rows:
            writer.writerow(existing_row)
        writer.writerow(normalized_row)

    return result_path


def start_benchmark_tracker():
    """Start timing and optional memory tracking for a script run."""
    benchmark_timer = timer(verbose=False)
    benchmark_timer.__enter__()

    benchmark_memory = None
    if choose_backend is not None:
        benchmark_memory = memory_logger(max_usage=False, timestamps=False)
        benchmark_memory.__enter__()

    return benchmark_timer, benchmark_memory


def finish_benchmark_tracker(result_path, rule_name: str, benchmark_timer, benchmark_memory):
    """Stop the tracker and append a benchmark row to result_path."""
    if benchmark_memory is not None:
        benchmark_memory.__exit__(None, None, None)
    benchmark_timer.__exit__(None, None, None)

    elapsed_seconds = benchmark_timer.usec / 1e6
    max_memory = "NA"
    memory_measurements = "NA"
    if benchmark_memory is not None and getattr(benchmark_memory, "mem_usage", None):
        max_memory = max(benchmark_memory.mem_usage)
        memory_measurements = getattr(benchmark_memory, "n_measurements", "NA")

    row = {
        "rule_name": rule_name,
        "elapsed_seconds": f"{elapsed_seconds:.4f}",
        "h:m:s": str(timedelta(seconds=elapsed_seconds)),
        "max_memory": max_memory,
        "memory_measurements": memory_measurements,
    }
    return append_benchmark_row(result_path, row)


def append_benchmark_csv(result_path, benchmark_path) -> Path:
    """Append one Snakemake benchmark TSV file into a consolidated CSV file."""
    benchmark_path = Path(benchmark_path)
    result_path = Path(result_path)
    result_path.parent.mkdir(parents=True, exist_ok=True)

    with benchmark_path.open("r", encoding="utf-8") as benchmark_stream:
        reader = csv.DictReader(benchmark_stream, delimiter="\t")
        benchmark_rows = [dict(row) for row in reader]
        benchmark_fields = list(reader.fieldnames or [])

    if not benchmark_rows:
        return result_path

    existing_rows = []
    existing_fields = []
    if result_path.exists():
        with result_path.open("r", encoding="utf-8", newline="") as result_stream:
            reader = csv.DictReader(result_stream)
            existing_fields = list(reader.fieldnames or [])
            existing_rows = [dict(row) for row in reader]

    merged_fields = []
    for field in existing_fields + benchmark_fields:
        if field and field not in merged_fields:
            merged_fields.append(field)

    merged_rows = existing_rows + benchmark_rows

    with result_path.open("w", encoding="utf-8", newline="") as result_stream:
        writer = csv.DictWriter(result_stream, fieldnames=merged_fields)
        writer.writeheader()
        writer.writerows(merged_rows)

    return result_path


class optional:
    def __init__(self, variable, contextman):
        self.variable = variable
        self.contextman = contextman

    def __enter__(self):
        if self.variable:
            return self.contextman.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.variable:
            return self.contextman.__exit__(exc_type, exc_val, exc_tb)
        return False
