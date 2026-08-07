"""두 번째 OMX: 합격(PASS) 바구니 처리 동작.

담당: 5번. 검사 결과가 PASS일 때만 호출된다.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from common.constants import RobotId, RobotState
from common.messages import InspectionResult, RobotStatus
from common.omx_controller import OmxCancelled, OmxController


# --------------------------------------------------
# PASS waypoint JSON 경로
# --------------------------------------------------
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
PASS_PATH = CONFIG_DIR / "pass_waypoints.json"


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
        # 3. JSON 읽기
        # --------------------------------------------------
        data = json.loads(
            PASS_PATH.read_text(encoding="utf-8")
        )

        sequence = data.get("sequence", [])

        if not sequence:
            return RobotStatus(
                RobotId.SORTING,
                RobotState.ERROR,
                success=False,
                message="PASS sequence가 비어 있습니다.",
            )

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

            action = step.get("action")

            print(
                f"[PASS {index}/{len(sequence)}] "
                f"{action}"
            )

            # ------------------------------
            # MOVE
            # ------------------------------
            if action == "move":
                angles = step.get("angles")

                if angles is None:
                    raise ValueError(
                        f"Step {index}: angles 값이 없습니다."
                    )

                duration = float(
                    step.get("duration", 2.0)
                )

                controller.move_joints_smooth(
                    angles,
                    duration=duration,
                )

            # ------------------------------
            # GRIPPER CLOSE
            # ------------------------------
            elif action == "gripper_close":
                duration = float(
                    step.get("duration", 1.0)
                )

                controller.gripper_close(
                    duration=duration
                )

            # ------------------------------
            # GRIPPER OPEN
            # ------------------------------
            elif action == "gripper_open":
                duration = float(
                    step.get("duration", 1.0)
                )

                controller.gripper_open(
                    duration=duration
                )

            # ------------------------------
            # 알 수 없는 action
            # ------------------------------
            else:
                raise ValueError(
                    f"Step {index}: "
                    f"지원하지 않는 action입니다: {action}"
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