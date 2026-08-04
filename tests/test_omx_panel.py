from pathlib import Path

from system_monitor.ui.omx_panel import resource_status


def test_resource_status_reports_missing_files(tmp_path: Path) -> None:
    status = resource_status(
        tmp_path / "calibration.json",
        tmp_path / "teaching.json",
    )

    assert status == "좌표 보정 없음 · Mouse 관절 교시 필요"


def test_resource_status_reports_invalid_teaching_file(tmp_path: Path) -> None:
    teaching = tmp_path / "teaching.json"
    teaching.write_text("not-json", encoding="utf-8")

    status = resource_status(tmp_path / "calibration.json", teaching)

    assert status == "좌표 보정 없음 · 교시 파일 오류"
