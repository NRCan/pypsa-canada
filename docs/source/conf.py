from datetime import datetime
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

project = "pypsa_canada"
author = "PyPSA Canada contributors"
copyright = f"{datetime.now().year}, {author}"

try:
    from pypsa_canada.__version__ import __version__ as release
except Exception:
    release = "unknown"

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.autosummary",
    "sphinx.ext.napoleon",
    "sphinx.ext.viewcode",
    "sphinx.ext.intersphinx",
]

templates_path = ["_templates"]
exclude_patterns = ["_build", "Thumbs.db", ".DS_Store"]

autosummary_generate = True
autodoc_typehints = "description"
autodoc_member_order = "bysource"
autodoc_default_options = {
    "members": True,
    "undoc-members": False,
    "show-inheritance": True,
}

autodoc_mock_imports = [
    "pypsa",
    "snakemake",
    "fiona",
    "matplotlib",
    "scipy",
    "pint",
    "pytz",
    "sklearn",
    "sklearn_extra",
    "folium",
]

intersphinx_mapping = {
    "python": ("https://docs.python.org/3", None),
}

html_theme = "sphinx_rtd_theme"
html_static_path = ["_static"]

rst_epilog = """
.. |workflow_scripts| replace:: pypsa_canada.workflow.scripts
.. |workflow_rep_days| replace:: pypsa_canada.workflow.scripts.representative_days
"""
