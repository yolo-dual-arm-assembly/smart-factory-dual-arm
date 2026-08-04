"""공정 상태 전이 규칙.

담당: 1번(통합). 로봇이나 카메라를 알지 않는 순수 로직이라 장비 없이도
테스트할 수 있다. 상태 문자열은 :class:`common.constants.RobotState`만 쓴다.
"""
from __future__ import annotations

from common.constants import RobotState

# 각 상태에서 넘어갈 수 있는 다음 상태. 여기 없는 전이는 버그로 본다.
ALLOWED_TRANSITIONS: dict[RobotState, tuple[RobotState, ...]] = {
    RobotState.IDLE: (RobotState.LOADING, RobotState.ERROR),
    RobotState.LOADING: (RobotState.LOADING_COMPLETE, RobotState.ERROR),
    RobotState.LOADING_COMPLETE: (RobotState.INSPECTING, RobotState.ERROR),
    RobotState.INSPECTING: (RobotState.PASS, RobotState.REJECT, RobotState.ERROR),
    RobotState.PASS: (RobotState.MOVING, RobotState.ERROR),
    RobotState.REJECT: (RobotState.MOVING, RobotState.ERROR),
    RobotState.MOVING: (RobotState.COMPLETE, RobotState.ERROR),
    RobotState.COMPLETE: (RobotState.IDLE,),
    RobotState.ERROR: (RobotState.IDLE,),
}


class InvalidTransition(RuntimeError):
    """허용되지 않은 상태 전이."""


class StateMachine:
    """현재 상태를 들고 전이 가능 여부를 판단한다."""

    def __init__(self, state: RobotState = RobotState.IDLE) -> None:
        self.state = state
        self.history: list[RobotState] = [state]

    def can_move_to(self, target: RobotState) -> bool:
        return target in ALLOWED_TRANSITIONS[self.state]

    def move_to(self, target: RobotState) -> RobotState:
        """상태를 옮긴다. 규칙에 없는 전이는 예외로 막는다."""
        if not self.can_move_to(target):
            raise InvalidTransition(
                f"{self.state} 상태에서 {target}(으)로 넘어갈 수 없습니다."
            )
        self.state = target
        self.history.append(target)
        return self.state

    def fail(self) -> RobotState:
        """어느 상태에서든 오류로 빠진다."""
        return self.move_to(RobotState.ERROR)

    def reset(self) -> RobotState:
        """작업을 끝내고 대기 상태로 돌아간다."""
        return self.move_to(RobotState.IDLE)
