"""두 번째 OMX: 합격(PASS) 바구니 처리 동작.

담당: 5번. 검사 결과가 PASS일 때만 호출된다.
"""
from __future__ import annotations

import time
from pathlib import Path

from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxCancelled, OmxController

from omx2_sorting.waypoints import load_waypoint_plan


# --------------------------------------------------
# PASS waypoint JSON 경로
# --------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
PASS_PATH = CONFIG_DIR / "pass_waypoints.json"


def run(controller: OmxController, inspection: InspectionResult) -> RobotStatus:
    """합격 바구니를 통과 라인으로 보낸다."""

    # --------------------------------------------------
    # 1. 검사 결과 확인
    # --------------------------------------------------
    if not inspection.is_pass:
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message="PASS 결과가 아닌데 통과 동작이 호출되었습니다.",
        )

    # --------------------------------------------------
    # 2. PASS waypoint JSON 존재 여부 확인
    # --------------------------------------------------
    if not PASS_PATH.exists():
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"PASS waypoint 파일이 없습니다: {PASS_PATH}",
        )

    try:
        # --------------------------------------------------
        # 3. 전체 계획 사전 검증
        # --------------------------------------------------
        plan = load_waypoint_plan(
            PASS_PATH,
            expected_motion="PASS",
        )
        sequence = plan.steps

        print("\n=== OMX2 PASS Motion 시작 ===")
        print(f"파일: {PASS_PATH}")
        print(f"Step 개수: {len(sequence)}")

        # --------------------------------------------------
        # 4. Torque ON
        # --------------------------------------------------
        controller.enable_torque()

        # --------------------------------------------------
        # 5. Sequence 순서대로 실행
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
                f"[PASS {index}/{len(sequence)}] "
                f"{action}"
            )

            # ------------------------------
            # MOVE
            # ------------------------------
            if action == "move":
                assert step.angles is not None

                controller.move_joints_smooth(
                    step.angles,
                    duration=step.duration,
                )

            # ------------------------------
            # GRIPPER CLOSE
            # ------------------------------
            elif action == "gripper_close":
                controller.gripper_close(
                    duration=step.duration
                )

            # ------------------------------
            # GRIPPER OPEN
            # ------------------------------
            elif action == "gripper_open":
                controller.gripper_open(
                    duration=step.duration
                )

            # Step 사이 안정화 시간
            time.sleep(0.3)

        print("=== OMX2 PASS Motion 완료 ===")

        # --------------------------------------------------
        # 6. 정상 완료 상태 반환
        # --------------------------------------------------
        return RobotStatus(
            RobotId.SORTING,
            RobotState.COMPLETE,
            success=True,
            message="PASS 바구니 분류 완료",
        )

    except OmxCancelled as cancelled:
        print(f"=== OMX2 PASS Motion 중단: {cancelled} ===")

        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message="PASS 동작이 중단되었습니다.",
        )

    except Exception as error:
        print(f"[PASS ERROR] {error}")

        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"PASS 동작 실패: {error}",
        )
