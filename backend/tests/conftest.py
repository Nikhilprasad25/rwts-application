import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
os.environ.setdefault("RWTS_STORAGE", tempfile.mkdtemp(prefix="rwts-test-"))

import pytest                                             # noqa: E402

SAMPLE = ROOT.parent / "sample_data" / "contacts.Exp1.xls"


@pytest.fixture(scope="session")
def sample_path() -> Path:
    assert SAMPLE.exists(), f"sample dataset missing at {SAMPLE}"
    return SAMPLE


@pytest.fixture(scope="session")
def prepared_dataset(sample_path):
    from app.data import dataset_manager as dm
    meta = dm.register_local_file(sample_path)
    did = meta["dataset_id"]
    sugg = dm.mapping_suggestions(did)
    mapping = {s["field"]: s["suggested_column"] for s in sugg["suggestions"]}
    dm.prepare(did, None, mapping, None)
    return did
