"""두 번째 OMX: 바구니를 검사 위치로 옮긴다.

담당: 5번. 관절 통신은 :mod:`common.omx_controller`를 그대로 쓰고, 여기서는
동작 순서만 정의한다. 반환값은 :class:`common.messages.RobotStatus` 하나로
고정해 통합 담당자가 상태만 보고 다음 단계를 진행할 수 있게 한다.
"""
from __future__ import annotations

from common.constants import RobotId, RobotState
from common.messages import RobotPosition, RobotStatus
from common.omx_controller import OmxConfig, OmxController


def move_to_inspection(
    controller: OmxController, position: RobotPosition
) -> RobotStatus:
    """바구니를 검사 위치로 옮긴다.

    TODO(5번): OmxController로 이동 시퀀스를 구현한다. 참고할 이동 예시는
    ``omx1_loading/imitation_control.py``에 있다.
    """
    raise NotImplementedError(
        "검사 위치 이동을 구현하세요. 성공하면 "
        "RobotStatus(RobotId.SORTING, RobotState.MOVING)을 반환합니다."
    )


def open_controller(port: str | None = None) -> OmxController:
    """분류 로봇 연결을 연다."""
    config = OmxConfig() if port is None else OmxConfig(port=port)
    return OmxController(config)


__all__ = [
    "RobotId",
    "RobotState",
    "move_to_inspection",
    "open_controller",
]
