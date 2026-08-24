"""두 번째 OMX: 불합격(REJECT) 바구니 처리 동작.

담당: 5번. 검사 결과가 REJECT일 때만 호출된다. 실행 절차는
:mod:`omx2_sorting.motion_runner`가 PASS와 공유한다.
"""
from __future__ import annotations

from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxController

from omx2_sorting.motion_runner import REJECT_PATH, run_motion


def run(controller: OmxController, inspection: InspectionResult) -> RobotStatus:
    """불량 바구니를 재작업 라인으로 보낸다."""
    return run_motion(controller, inspection, expect_pass=False, path=REJECT_PATH)
