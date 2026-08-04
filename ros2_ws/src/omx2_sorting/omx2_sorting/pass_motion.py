"""두 번째 OMX: 합격(PASS) 바구니 처리 동작.

담당: 5번. 검사 결과가 PASS일 때만 호출된다.
"""
from __future__ import annotations

from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxController


def run(controller: OmxController, inspection: InspectionResult) -> RobotStatus:
    """합격 바구니를 통과 라인으로 보낸다.

    TODO(5번): 통과 위치 이동과 그리퍼 동작을 구현한다.
    """
    if not inspection.is_pass:
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message="PASS 결과가 아닌데 통과 동작이 호출되었습니다.",
        )
    raise NotImplementedError("통과 동작을 구현하세요.")
