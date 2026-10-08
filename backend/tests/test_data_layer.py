"""Reader, mapper, validator and transformer."""
import pandas as pd
import pytest

from app.data import excel_reader
from app.data.mapper import MappingError, apply_mapping, suggest_mapping, validate_mapping
from app.data.transformer import CleaningOptions, compute_contact_parameters, transform
from app.data.validator import validate


def test_detects_delimited_text_named_xls(sample_path):
    fmt, delim = excel_reader.detect_format(sample_path)
    assert fmt == "delimited-text"
    assert delim == "\t"


def test_synthetic_header_and_shape(sample_path):
    df, synthetic = excel_reader.read_sheet(sample_path)
    assert synthetic is True
    assert list(df.columns) == [f"col_{i}" for i in range(1, 7)]
    assert len(df) == 2766


def test_inspection_reports_missing_and_duplicates(sample_path):
    info = excel_reader.inspect_workbook(sample_path)
    sheet = info.sheets[0]
    assert sheet.rows == 2766 and sheet.columns == 6
    assert sum(sheet.missing_values.values()) == 0
    assert len(sheet.sample) == 10


def test_haggle_layout_is_suggested(sample_path):
    df, synthetic = excel_reader.read_sheet(sample_path)
    sugg = {s.field: s.suggested_column for s in suggest_mapping(df, synthetic)}
    assert sugg["source_worker"] == "col_1"
    assert sugg["destination_worker"] == "col_2"
    assert sugg["timestamp"] == "col_3"
    assert sugg["end_time"] == "col_4"


def test_real_xlsx_workbook_roundtrip(tmp_path):
    p = tmp_path / "book.xlsx"
    pd.DataFrame({"timestamp": [1, 2], "node_a": ["A", "B"],
                  "node_b": ["B", "C"], "duration": [5, 6]}).to_excel(p, index=False)
    fmt, _ = excel_reader.detect_format(p)
    assert fmt == "xlsx"
    df, synthetic = excel_reader.read_sheet(p)
    assert synthetic is False
    sugg = {s.field: s.suggested_column for s in suggest_mapping(df, False)}
    assert sugg["source_worker"] == "node_a"
    assert sugg["destination_worker"] == "node_b"
    assert sugg["duration"] == "duration"


def test_mapping_requires_required_fields():
    with pytest.raises(MappingError):
        validate_mapping({"timestamp": "t"}, ["t"])


def test_mapping_requires_duration_or_end_time():
    with pytest.raises(MappingError):
        validate_mapping({"timestamp": "t", "source_worker": "a",
                          "destination_worker": "b"}, ["t", "a", "b"])


def test_validator_flags_every_rule():
    df = pd.DataFrame({
        "timestamp": [0, 1, 2, None, 4],
        "source_worker": ["A", "A", "", "A", "A"],
        "destination_worker": ["B", "A", "B", "B", "B"],
        "duration": [1, 1, 1, 1, -3],
    })
    mask, rep = validate(df)
    assert rep.total_rows == 5
    assert rep.rule_counts["self_contact"] == 1
    assert rep.rule_counts["invalid_source"] == 1
    assert rep.rule_counts["invalid_timestamp"] == 1
    assert rep.rule_counts["negative_duration"] == 1
    assert mask.sum() == 1


def test_transform_funnel_counts_every_stage(sample_path):
    df, synthetic = excel_reader.read_sheet(sample_path)
    mapping = {s.field: s.suggested_column for s in suggest_mapping(df, synthetic)}
    res = transform(df, mapping, CleaningOptions())
    assert res.funnel[0].rows == 2766
    assert res.funnel[-1].stage == "Processed records"
    assert len(res.records) == res.funnel[-1].rows
    assert min(r.timestamp for r in res.records) == 0.0
    assert all(r.duration >= 0 for r in res.records)


def test_lambda_estimation_matches_definition(sample_path):
    df, synthetic = excel_reader.read_sheet(sample_path)
    mapping = {s.field: s.suggested_column for s in suggest_mapping(df, synthetic)}
    res = transform(df, mapping, CleaningOptions())
    params = compute_contact_parameters(res.records)
    assert len(params) > 5
    for p in list(params.values())[:5]:
        assert p.lam == pytest.approx(p.contact_count / p.observation_period, rel=1e-9)
        assert p.lam > 0
