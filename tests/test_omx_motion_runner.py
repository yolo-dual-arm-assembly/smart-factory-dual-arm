"""omx2_sorting.motion_runner의 PASS/REJECT 공유 실행 동작 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from common.messages import InspectionResult
from omx2_sorting import motion_runner


class RecordingController:
    def __init__(self) -> None:
        self.commands: list[str] = []

    def enable_torque(self) -> None:
        self.commands.append("enable_torque")

    def stop_requested(self) -> bool:
        return False

    def move_joints_smooth(self, *_args, **_kwargs) -> None:
        self.commands.append("move_joints_smooth")

    def gripper_open(self, *_args, **_kwargs) -> None:
        self.commands.append("gripper_open")

    def gripper_close(self, *_args, **_kwargs) -> None:
        self.commands.append("gripper_close")


def _write_plan(path: Path, *, motion: str) -> None:
    path.write_text(
        json.dumps(
            {
                "motion": motion,
                "step_count": 2,
                "sequence": [
                    {"action": "gripper_open", "duration": 0.01},
                    {"action": "gripper_close", "duration": 0.01},
                ],
            }
        ),
        encoding="utf-8",
    )


@pytest.mark.parametrize(
    ("expect_pass", "motion", "defect_count"),
    (
        (True, "PASS", 0),
        (False, "REJECT", 1),
    ),
)
def test_run_motion_completes_matching_verdict(
    tmp_path: Path,
    expect_pass: bool,
    motion: str,
    defect_count: int,
) -> None:
    path = tmp_path / "plan.json"
    _write_plan(path, motion=motion)
    controller = RecordingController()

    status = motion_runner.run_motion(
        controller,
        InspectionResult.from_counts(total_count=1, defect_count=defect_count),
        expect_pass=expect_pass,
        path=path,
    )

    assert status.success
    assert status.message == f"{motion} 바구니 분류 완료"
    assert controller.commands == ["enable_torque", "gripper_open", "gripper_close"]


@pytest.mark.parametrize(
    ("expect_pass", "defect_count", "expected_message"),
    (
        (True, 1, "PASS 결과가 아닌데 통과 동작이 호출되었습니다."),
        (False, 0, "PASS 결과인데 불량 배출 동작이 호출되었습니다."),
    ),
)
def test_run_motion_rejects_mismatched_verdict(
    tmp_path: Path,
    expect_pass: bool,
    defect_count: int,
    expected_message: str,
) -> None:
    """검사 방향과 요청한 동작 방향이 어긋나면 로봇을 아예 움직이지 않는다."""
    path = tmp_path / "plan.json"
    _write_plan(path, motion="PASS" if expect_pass else "REJECT")
    controller = RecordingController()

    status = motion_runner.run_motion(
        controller,
        InspectionResult.from_counts(total_count=1, defect_count=defect_count),
        expect_pass=expect_pass,
        path=path,
    )

    assert not status.success
    assert status.message == expected_message
    assert controller.commands == []


def test_run_motion_reports_missing_waypoint_file(tmp_path: Path) -> None:
    path = tmp_path / "missing.json"
    controller = RecordingController()

    status = motion_runner.run_motion(
        controller,
        InspectionResult.from_counts(total_count=1, defect_count=0),
        expect_pass=True,
        path=path,
    )

    assert not status.success
    assert "waypoint 파일이 없습니다" in status.message
    assert controller.commands == []


def test_run_motion_stops_when_cancel_requested_mid_sequence(tmp_path: Path) -> None:
    path = tmp_path / "plan.json"
    _write_plan(path, motion="PASS")

    class CancellingController(RecordingController):
        def __init__(self) -> None:
            super().__init__()
            self._calls = 0

        def stop_requested(self) -> bool:
            self._calls += 1
            return self._calls > 1  # 두 번째 스텝 시작 전에 중단 요청

    controller = CancellingController()

    status = motion_runner.run_motion(
        controller,
        InspectionResult.from_counts(total_count=1, defect_count=0),
        expect_pass=True,
        path=path,
    )

    assert not status.success
    assert status.message == "PASS 동작이 중단되었습니다."
    assert controller.commands == ["enable_torque", "gripper_open"]
