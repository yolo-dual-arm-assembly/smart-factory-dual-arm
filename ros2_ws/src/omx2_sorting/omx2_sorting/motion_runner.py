"""OMX2 PASS/REJECT 바구니 처리 동작의 공유 실행기.

``pass_motion.py``와 ``reject_motion.py``는 검사 결과 방향(PASS/REJECT)만
다르고 실행 절차는 완전히 동일했다. 그 절차를 여기 하나로 모아 두 얇은
래퍼가 재사용하게 한다 — 안전 관련 수정(중단 확인, 에러 처리 등)이 한쪽에만
반영되는 사고를 막는다.
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
PASS_PATH = CONFIG_DIR / "pass_waypoints.json"
REJECT_PATH = CONFIG_DIR / "reject_waypoints.json"


def run_motion(
    controller: OmxController,
    inspection: InspectionResult,
    *,
    expect_pass: bool,
    path: Path,
) -> RobotStatus:
    """PASS 또는 REJECT 바구니 처리 동작 하나를 실행한다.

    ``expect_pass``는 이 동작이 어느 방향인지, ``inspection.is_pass``는 검사가
    실제로 어느 방향으로 나왔는지다. 둘이 다르면 로봇을 움직이지 않고 바로
    에러를 반환한다 — 호출자가 판정을 잘못 연결한 것이지 로봇 문제가 아니다.
    연결·토크 설정은 호출자 책임이며, 여기서는 ``enable_torque()``만 한다.
    """
    motion = "PASS" if expect_pass else "REJECT"
    label = "통과" if expect_pass else "불량 배출"

    if inspection.is_pass != expect_pass:
        mismatch = "PASS 결과가 아닌데" if expect_pass else "PASS 결과인데"
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"{mismatch} {label} 동작이 호출되었습니다.",
        )

    if not path.exists():
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"{motion} waypoint 파일이 없습니다: {path}",
        )

    try:
        # 전체 계획을 먼저 검증한다 — 뒤쪽 스텝 하나가 잘못돼도 앞쪽 스텝은
        # 이미 로봇을 움직인 뒤일 수 있으므로, 실행 전에 전부 확인해 둔다.
        plan = load_waypoint_plan(path, expected_motion=motion)
        sequence = plan.steps

        print(f"\n=== OMX2 {motion} Motion 시작 ===")
        print(f"파일: {path}")
        print(f"Step 개수: {len(sequence)}")

        controller.enable_torque()

        for index, step in enumerate(sequence, start=1):
            # 중단은 스텝 경계에서도 확인한다. 이동 중에는 컨트롤러가
            # OmxCancelled를 던지지만, 대기 중이던 스텝은 여기서 걸린다.
            if controller.stop_requested():
                raise OmxCancelled(f"Step {index} 시작 전 중단되었습니다.")

            action = step.action
            print(f"[{motion} {index}/{len(sequence)}] {action}")

            if action == "move":
                assert step.angles is not None
                controller.move_joints_smooth(step.angles, duration=step.duration)
            elif action == "gripper_close":
                controller.gripper_close(duration=step.duration)
            elif action == "gripper_open":
                controller.gripper_open(duration=step.duration)

            # Step 사이 안정화 시간
            time.sleep(0.3)

        print(f"=== OMX2 {motion} Motion 완료 ===")

        return RobotStatus(
            RobotId.SORTING,
            RobotState.COMPLETE,
            success=True,
            message=f"{motion} 바구니 분류 완료",
        )

    except OmxCancelled as cancelled:
        print(f"=== OMX2 {motion} Motion 중단: {cancelled} ===")
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"{motion} 동작이 중단되었습니다.",
        )

    except Exception as error:
        print(f"[{motion} ERROR] {error}")
        return RobotStatus(
            RobotId.SORTING,
            RobotState.ERROR,
            success=False,
            message=f"{motion} 동작 실패: {error}",
        )
