"""OMX2 웨이포인트의 실행 전 안전 검증 테스트."""
from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from common.messages import InspectionResult
from omx2_sorting import pass_motion, reject_motion
from omx2_sorting.waypoints import load_waypoint_plan


def _write_plan(
    path: Path,
    *,
    motion: str = "PASS",
    steps: list[dict[str, object]],
    step_count: int | None = None,
) -> None:
    path.write_text(
        json.dumps(
            {
                "motion": motion,
                "step_count": len(steps) if step_count is None else step_count,
                "sequence": steps,
            }
        ),
        encoding="utf-8",
    )


class TestWaypointValidation:
    @pytest.mark.parametrize(
        ("path", "motion"),
        [
            (pass_motion.PASS_PATH, "PASS"),
            (reject_motion.REJECT_PATH, "REJECT"),
        ],
    )
    def test_repository_plans_are_valid(self, path: Path, motion: str) -> None:
        plan = load_waypoint_plan(path, expected_motion=motion)

        assert plan.motion == motion
        assert plan.steps

    def test_rejects_step_count_mismatch(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_count.json"
        _write_plan(
            path,
            steps=[{"action": "gripper_open", "duration": 1.0}],
            step_count=2,
        )

        with pytest.raises(ValueError, match="step_count 불일치"):
            load_waypoint_plan(path, expected_motion="PASS")

    @pytest.mark.parametrize("duration", [0, -1, math.inf, math.nan, True])
    def test_rejects_invalid_duration(
        self,
        tmp_path: Path,
        duration: object,
    ) -> None:
        path = tmp_path / "bad_duration.json"
        _write_plan(
            path,
            steps=[{"action": "gripper_open", "duration": duration}],
        )

        with pytest.raises(ValueError, match="duration"):
            load_waypoint_plan(path, expected_motion="PASS")

    def test_rejects_unknown_action(self, tmp_path: Path) -> None:
        path = tmp_path / "bad_action.json"
        _write_plan(
            path,
            steps=[{"action": "drop_basket", "duration": 1.0}],
        )

        with pytest.raises(ValueError, match="지원하지 않는 action"):
            load_waypoint_plan(path, expected_motion="PASS")


class TestWaypointFailClosed:
    def test_late_invalid_joint_prevents_every_robot_command(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        path = tmp_path / "late_invalid.json"
        _write_plan(
            path,
            steps=[
                {"action": "gripper_open", "duration": 1.0},
                {
                    "action": "move",
                    "angles": [0.0, math.pi, 0.0, 0.0, 0.0],
                    "duration": 2.0,
                },
            ],
        )
        monkeypatch.setattr(pass_motion, "PASS_PATH", path)

        class RecordingController:
            def __init__(self) -> None:
                self.commands: list[str] = []

            def enable_torque(self) -> None:
                self.commands.append("enable_torque")

            def stop_requested(self) -> bool:
                self.commands.append("stop_requested")
                return False

            def move_joints_smooth(self, *_args, **_kwargs) -> None:
                self.commands.append("move_joints_smooth")

            def gripper_open(self, *_args, **_kwargs) -> None:
                self.commands.append("gripper_open")

            def gripper_close(self, *_args, **_kwargs) -> None:
                self.commands.append("gripper_close")

        controller = RecordingController()

        status = pass_motion.run(
            controller,  # type: ignore[arg-type]
            InspectionResult.from_counts(total_count=1, defect_count=0),
        )

        assert not status.success
        assert "Joint 2 한계 초과" in status.message
        assert controller.commands == []
