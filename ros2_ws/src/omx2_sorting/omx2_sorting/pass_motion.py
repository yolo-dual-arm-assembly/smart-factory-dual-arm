"""두 번째 OMX: 합격(PASS) 바구니 처리 동작.

담당: 5번. 검사 결과가 PASS일 때만 호출된다. 실행 절차는
:mod:`omx2_sorting.motion_runner`가 REJECT와 공유한다.
"""
from __future__ import annotations

from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxController

from omx2_sorting.motion_runner import PASS_PATH, run_motion


def run(controller: OmxController, inspection: InspectionResult) -> RobotStatus:
    """합격 바구니를 통과 라인으로 보낸다."""
    return run_motion(controller, inspection, expect_pass=True, path=PASS_PATH)
