"""Runs the exact PY_PIPELINE script extracted from app.js against synthetic fixture
files (web/_synth/, no real/personal data), through the real CPython interpreter + the
real itr_assist package (same code Pyodide will run), to catch logic/import errors
before any browser testing."""
import json
import sys, os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))  # use the real repo's itr_assist, identical to what's in the wheel

SYNTH = os.path.join(os.path.dirname(__file__), "_synth")

pipeline_src = open(os.path.join(os.path.dirname(__file__), "_extracted_pipeline.py"), encoding="utf-8").read()

# The pipeline hardcodes /uploads/*.pdf paths (matches Pyodide's virtual FS layout) -
# redirect them to the real synthetic files on disk for this test.
pipeline_src = pipeline_src.replace('"/uploads/benefit.xlsx"', repr(os.path.join(SYNTH, "benefit.xlsx")))
pipeline_src = pipeline_src.replace('"/uploads/holdings.xlsx"', repr(os.path.join(SYNTH, "holdings.xlsx")))
pipeline_src = pipeline_src.replace('"/uploads/taxdoc.pdf"', repr(os.path.join(SYNTH, "taxdoc.pdf")))
pipeline_src = pipeline_src.replace('"/output/ITR_Schedules.xlsx"', repr(os.path.join(SYNTH, "ITR_Schedules.xlsx")))

stmt_paths = [os.path.join(SYNTH, "stmt_cy.pdf"), os.path.join(SYNTH, "stmt_fy.pdf")]
glb = {
    "fy": "2025-26",
    "taxpayer_name": "",
    "pan": "",
    "stmt_paths_json": json.dumps(stmt_paths),
    "market_api_key": "",
}
exec(compile(pipeline_src, "<pipeline>", "exec"), glb)
print("RESULT:")
print(glb["result"])
