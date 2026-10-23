"""Layout, geometry, flow, and summary defaults for corridor maps."""

POPUP_WIDTH = 760
POPUP_HEIGHT = 520

FORCE_TIME_COL = None

CURVE_OFFSET_M = 3500.0
PARALLEL_STEP_M = 1800.0
SELF_LOOP_RADIUS_M = 2500.0
SELF_LOOP_STEP_M = 900.0

BUS_JITTER_M = 900.0
BUS_JITTER_MODE = "suffix_voltage"

POST_PROCESS_FILE_GLOB = "**/*_hourly*.csv"

CONGESTION_THRESHOLD = 0.8
FULL_CAPACITY_LINE = 1.0

LINE_COLOR_WITH_DATA = "#3388ff"
LINE_COLOR_NO_DATA = "#888888"
_NEW_LINE_BADGE = '<span style="color:#22bb44"><b>[NEW]</b></span> '

SUMMARY_COLUMNS = [
    "case",
    "corridor",
    "busA",
    "busB",
    "provinceA",
    "provinceB",
    "corridor_capacity_mw",
    "capacity_for_utilization_mw",
    "existing_lines_capacity_mw",
    "new_lines_capacity_mw",
    "provincial_aggregation_used",
    "max_utilization",
    "avg_utilization",
    "hours_ge_0_8",
    "hours_ge_1_0",
    "flow_orientation",
]
