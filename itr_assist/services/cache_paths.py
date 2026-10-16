"""Where downloaded reference data (SBI rates, daily stock prices) is cached."""
import os

CACHE_DIR_ENV = "ITR_ASSIST_CACHE_DIR"
# Snapshot of the SBI TT buying rate history shipped inside the package, used only when the
# live download fails and nothing is cached yet (offline first run, or a blocked network).
BUNDLED_SBI_CSV = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "SBI_REFERENCE_RATES_USD.csv")


def default_cache_dir() -> str:
    """Per-user cache directory. Never relative to the current working directory - running the
    tool from another folder (e.g. C:\\Windows\\System32) must not litter it with data/cache."""
    return os.environ.get(CACHE_DIR_ENV) or os.path.join(os.path.expanduser("~"), ".itr_assist", "cache")
