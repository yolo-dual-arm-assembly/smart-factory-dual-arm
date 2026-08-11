"""OMX2 PASS/REJECT 웨이포인트 파일의 하드웨어 독립 검증."""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from typing import Any

from common.omx_controller import validate_joint_angles


SUPPORTED_ACTIONS = frozenset({"move", "gripper_close", "gripper_open"})


@dataclass(frozen=True)
class WaypointStep:
    """검증을 마친 단일 분류 동작."""

    action: str
    duration: float
    angles: tuple[float, ...] | None = None


@dataclass(frozen=True)
class WaypointPlan:
    """검증을 마친 PASS 또는 REJECT 동작 계획."""

    motion: str
    steps: tuple[WaypointStep, ...]


def _positive_duration(value: object, *, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ValueError(f"{label}: duration은 0보다 큰 숫자여야 합니다.")

    duration = float(value)
    if not math.isfinite(duration) or duration <= 0:
        raise ValueError(
            f"{label}: duration은 0보다 큰 유한한 값이어야 합니다 "
            f"(입력: {duration!r})."
        )
    return duration


def load_waypoint_plan(path: Path, *, expected_motion: str) -> WaypointPlan:
    """웨이포인트 전체를 읽고 검증한다.

    로봇 연결이나 토크 활성화 전에 호출해야 한다. 뒤쪽 스텝 하나라도
    잘못되면 계획 전체가 거부되므로 앞쪽의 정상 스텝도 실행되지 않는다.
    """
    if not path.is_file():
        raise FileNotFoundError(f"waypoint 파일이 없습니다: {path}")

    try:
        raw: Any = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as error:
        raise ValueError(
            f"waypoint JSON 형식이 잘못되었습니다: {path} "
            f"({error.msg}, line {error.lineno})"
        ) from error

    if not isinstance(raw, dict):
        raise ValueError("waypoint 최상위 값은 객체여야 합니다.")

    motion = raw.get("motion")
    if motion != expected_motion:
        raise ValueError(
            f"motion 불일치: {motion!r} != {expected_motion!r}"
        )

    raw_steps = raw.get("sequence")
    if not isinstance(raw_steps, list) or not raw_steps:
        raise ValueError(
            f"{expected_motion} sequence는 비어 있지 않은 목록이어야 합니다."
        )

    step_count = raw.get("step_count")
    if (
        isinstance(step_count, bool)
        or not isinstance(step_count, int)
        or step_count != len(raw_steps)
    ):
        raise ValueError(
            f"step_count 불일치: {step_count!r} != {len(raw_steps)}"
        )

    steps: list[WaypointStep] = []
    for index, raw_step in enumerate(raw_steps, start=1):
        label = f"{expected_motion} Step {index}"
        if not isinstance(raw_step, dict):
            raise ValueError(f"{label}: 각 step은 객체여야 합니다.")

        action = raw_step.get("action")
        if not isinstance(action, str) or action not in SUPPORTED_ACTIONS:
            raise ValueError(
                f"{label}: 지원하지 않는 action입니다: {action!r}"
            )

        default_duration = 2.0 if action == "move" else 1.0
        duration = _positive_duration(
            raw_step.get("duration", default_duration),
            label=label,
        )

        angles: tuple[float, ...] | None = None
        if action == "move":
            raw_angles = raw_step.get("angles")
            if not isinstance(raw_angles, list):
                raise ValueError(
                    f"{label}: angles는 숫자 목록이어야 합니다."
                )
            angles = tuple(validate_joint_angles(raw_angles, label=label))

        steps.append(
            WaypointStep(
                action=action,
                duration=duration,
                angles=angles,
            )
        )

    return WaypointPlan(motion=expected_motion, steps=tuple(steps))
