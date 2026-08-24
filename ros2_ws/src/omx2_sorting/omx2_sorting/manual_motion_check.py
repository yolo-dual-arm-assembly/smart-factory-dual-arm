"""OMX2 PASS/REJECT 동작을 실제 장비로 수동 확인.

``pass_motion.run()``/``reject_motion.run()``이 프로덕션에서 쓰는 것과 동일한
:func:`omx2_sorting.motion_runner.run_motion`을 그대로 호출한다. 예전
``test_motion.py``/``test_motion_reject.py``처럼 실행 루프를 따로 복사하지
않으므로, 여기서 확인한 동작이 실제 운영 경로와 달라질 위험이 없다.

기본 사용(레포 루트에서 실행):
    python -m omx2_sorting.manual_motion_check --motion pass
    python -m omx2_sorting.manual_motion_check --motion reject
"""
from __future__ import annotations

import argparse
import time

from common.messages import InspectionResult
from common.omx_controller import OmxController

from omx2_sorting.motion_runner import PASS_PATH, REJECT_PATH, run_motion
from omx2_sorting.waypoints import load_waypoint_plan


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="OMX2 PASS/REJECT 동작을 실제 장비로 실행합니다."
    )
    parser.add_argument(
        "--motion",
        choices=("pass", "reject"),
        required=True,
        help="확인할 동작",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    expect_pass = args.motion == "pass"
    motion = "PASS" if expect_pass else "REJECT"
    path = PASS_PATH if expect_pass else REJECT_PATH

    print(f"\n=== OMX2 {motion} Motion 수동 확인 ===")
    print(f"불러올 파일: {path}")

    if not path.exists():
        print(f"[ERROR] JSON 파일이 없습니다: {path}")
        return

    plan = load_waypoint_plan(path, expected_motion=motion)
    print(f"Step 개수: {len(plan.steps)}")
    print("\n실행 순서:")
    for index, step in enumerate(plan.steps, start=1):
        print(f"{index}. {step.action}")

    confirm = input("\n실제 OMX2를 움직입니다. 실행할까요? (y/n): ").strip().lower()
    if confirm != "y":
        print("실행 취소")
        return

    # 판정을 다시 하지 않는다 — 확인하려는 동작 방향과 같은 검사 결과를
    # 그 자리에서 만들어 run_motion의 방향 검사만 통과시킨다.
    inspection = InspectionResult.from_counts(
        total_count=1, defect_count=0 if expect_pass else 1
    )

    controller = OmxController()
    try:
        controller.connect()
        print("\n[OMX2 연결 완료]")
        print("3초 후 동작을 시작합니다...")
        time.sleep(3)

        status = run_motion(
            controller, inspection, expect_pass=expect_pass, path=path
        )
        print(f"\n결과: success={status.success} message={status.message}")

    except KeyboardInterrupt:
        print("\n사용자가 확인을 중단했습니다.")

    except Exception as error:
        print(f"\n[ERROR] {error}")

    finally:
        controller.disconnect()
        print("OMX2 연결 종료")


if __name__ == "__main__":
    main()
