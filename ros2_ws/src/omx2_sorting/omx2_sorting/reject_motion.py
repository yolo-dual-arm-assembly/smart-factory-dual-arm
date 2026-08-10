"""두 번째 OMX: 불합격(REJECT) 바구니 처리 동작.

담당: 5번. 검사 결과가 REJECT일 때만 호출된다.
"""
from __future__ import annotations

import time
from pathlib import Path

from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxCancelled, OmxController

from omx2_sorting.waypoints import load_waypoint_plan


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
REJECT_PATH = CONFIG_DIR / "reject_waypoints.json"


def run(controller: OmxController, inspection: InspectionResult) -> RobotStatus:
    """불량 바구니를 재작업 라인으로 보낸다."""

    # --------------------------------------------------
    # 1. REJECT 결과인지 확인
    # --------------------------------------------------
    if inspection.is_pass:
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message="PASS 결과인데 불량 배출 동작이 호출되었습니다.",
        )

    # --------------------------------------------------
    # 2. JSON 파일 확인
    # --------------------------------------------------
    if not REJECT_PATH.exists():
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"REJECT waypoint 파일이 없습니다: {REJECT_PATH}",
        )

    try:
        # --------------------------------------------------
        # 3. REJECT 전체 계획 사전 검증
        # --------------------------------------------------
        plan = load_waypoint_plan(
            REJECT_PATH,
            expected_motion="REJECT",
        )
        sequence = plan.steps

        print("\n=== OMX2 REJECT Motion 시작 ===")
        print(f"파일: {REJECT_PATH}")
        print(f"Step 개수: {len(sequence)}")

        # --------------------------------------------------
        # 4. Torque ON
        # --------------------------------------------------
        controller.enable_torque()

        # --------------------------------------------------
        # 5. JSON sequence 순서대로 실행
        # --------------------------------------------------
        for index, step in enumerate(sequence, start=1):
            # 중단은 스텝 경계에서도 확인한다. 이동 중에는 컨트롤러가
            # OmxCancelled를 던지지만, 대기 중이던 스텝은 여기서 걸린다.
            if controller.stop_requested():
                raise OmxCancelled(
                    f"Step {index} 시작 전 중단되었습니다."
                )

            action = step.action

            print(
                f"[REJECT {index}/{len(sequence)}] "
                f"{action}"
            )

            # MOVE
            if action == "move":
                assert step.angles is not None

                controller.move_joints_smooth(
                    step.angles,
                    duration=step.duration,
                )

            # GRIPPER CLOSE
            elif action == "gripper_close":
                controller.gripper_close(
                    duration=step.duration
                )

            # GRIPPER OPEN
            elif action == "gripper_open":
                controller.gripper_open(
                    duration=step.duration
                )

            # Step 사이 짧은 안정화 시간
            time.sleep(0.3)

        print("=== OMX2 REJECT Motion 완료 ===")

        # --------------------------------------------------
        # 6. 정상 완료
        # --------------------------------------------------
        return RobotStatus(
            RobotId.SORTING,
            RobotState.COMPLETE,
            success=True,
            message="REJECT 바구니 분류 완료",
        )

    except OmxCancelled as cancelled:
        print(f"=== OMX2 REJECT Motion 중단: {cancelled} ===")

        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message="REJECT 동작이 중단되었습니다.",
        )

    except Exception as error:
        print(f"[REJECT ERROR] {error}")

        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"REJECT 동작 실패: {error}",
        )
