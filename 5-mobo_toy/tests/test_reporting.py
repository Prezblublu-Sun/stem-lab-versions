"""报告工具链测试：登记表一致性、产物四件套、只凭 CSV 重画、验收状态校验。"""
import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import plotstyle as ps  # noqa: E402
import report  # noqa: E402


def test_spec_ids_unique_and_prefixed():
    spec = ps.load_spec()
    seen = set()
    for rid, rep in spec["reports"].items():
        for kind, tag in (("figures", "F"), ("tables", "T"), ("acceptance", "A")):
            for item in rep.get(kind, []):
                assert item["id"].startswith(f"{rid}-{tag}"), item["id"]
                assert item["id"] not in seen, f"重复编号 {item['id']}"
                seen.add(item["id"])
        for key in ("dir", "title", "stage", "cou", "question", "not_answered"):
            assert rep.get(key), f"{rid} 缺 {key}"
        assert rep.get("acceptance"), f"{rid} 没有验收项"


def test_every_stage_has_plottable_report():
    """用户要求：每个阶段都有可作图的结果报告。"""
    spec = ps.load_spec()
    stages = {r["stage"] for r in spec["reports"].values() if not r.get("demo")}
    assert {"S0", "S1", "S2", "S3", "S4", "S5", "S7", "close"} <= stages
    for rid, rep in spec["reports"].items():
        assert len(rep["figures"]) >= 1, f"{rid} 没有必备图"


def test_demo_pipeline_and_replot(tmp_path):
    import demo_report
    demo_report.make()
    d = ps.report_dir("RD")
    for fid in ("RD-F01", "RD-F02", "RD-F03"):
        for ext in ("png", "svg", "csv", "json"):
            assert (d / "figures" / f"{fid}.{ext}").exists(), f"{fid}.{ext}"
        meta = json.loads((d / "figures" / f"{fid}.json").read_text(encoding="utf-8"))
        assert meta["synthetic"] is True and meta["csv_sha256"]
        # 只凭 CSV 重画，SVG 应与原图逐字节相同（hashsalt 固定、去掉日期）
        out = ps.replot(fid, out_suffix="_replot")
        assert out.read_bytes() == (d / "figures" / f"{fid}.svg").read_bytes()
        out.unlink()
        (d / "figures" / f"{fid}_replot.png").unlink()
    c = report.collect("RD", ps.load_spec())
    assert c["synthetic"]
    assert report.verdict(c) == "INCOMPLETE"          # RD-A3 故意未提交
    assert any(i == "RD-A3" for _, i, _ in c["missing"])


def test_acceptance_validation():
    with pytest.raises(KeyError):
        ps.publish_acceptance("RD", [{"id": "R2-A1", "status": "PASS"}])
    with pytest.raises(ValueError):
        ps.publish_acceptance("RD", [{"id": "RD-A2", "status": "FAIL"}])     # FAIL 必须写 note
    with pytest.raises(ValueError):
        ps.publish_acceptance("RD", [{"id": "RD-A1", "status": "OK"}])       # 非法状态


def test_empty_data_rejected(tmp_path):
    with pytest.raises(ValueError):
        ps.write_csv(tmp_path / "x.csv", [])


def test_tamper_detected():
    import demo_report
    demo_report.make()
    d = ps.report_dir("RD") / "figures"
    p = d / "RD-F03.csv"
    original = p.read_bytes()
    try:
        p.write_bytes(original + b"C,1.0,1.0,0\n")
        c = report.collect("RD", ps.load_spec())
        assert "RD-F03" in c["tampered"]
        with pytest.raises(RuntimeError):
            ps.replot("RD-F03")
    finally:
        p.write_bytes(original)
