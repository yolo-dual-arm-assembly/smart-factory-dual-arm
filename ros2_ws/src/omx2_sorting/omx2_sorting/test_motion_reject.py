import time
from pathlib import Path

from common.omx_controller import OmxController

from omx2_sorting.waypoints import load_waypoint_plan


PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
REJECT_PATH = CONFIG_DIR / "reject_waypoints.json"


def run_reject_motion():
    """저장된 REJECT sequence를 순서대로 실행한다."""

    if not REJECT_PATH.exists():
        raise FileNotFoundError(
            f"REJECT waypoint 파일이 없습니다: {REJECT_PATH}"
        )

    plan = load_waypoint_plan(
        REJECT_PATH,
        expected_motion="REJECT",
    )
    sequence = plan.steps

    print("\n=== OMX2 REJECT Motion ===")
    print(f"파일: {REJECT_PATH}")
    print(f"Step 개수: {len(sequence)}")

    controller = OmxController()

    try:
        controller.connect()
        controller.enable_torque()

        print("\n[OMX2 연결 완료]")
        print("3초 후 REJECT 동작을 시작합니다...")
        time.sleep(3)

        for index, step in enumerate(sequence, start=1):
            action = step.action

            print(
                f"\n[Step {index}/{len(sequence)}] "
                f"{action}"
            )

            if action == "move":
                assert step.angles is not None

                # 첫 테스트는 천천히.
                # 정상 동작 확인 후 JSON duration을 쓰도록 변경 가능.
                duration = 2.0

                controller.move_joints_smooth(
                    step.angles,
                    duration=duration,
                )

            elif action == "gripper_close":
                controller.gripper_close(
                    duration=step.duration
                )

            elif action == "gripper_open":
                controller.gripper_open(
                    duration=step.duration
                )

            time.sleep(0.3)

        print("\n=== REJECT Motion 완료 ===")

    finally:
        controller.disconnect()
        print("OMX2 연결 종료")


def main():
    print("\n=== REJECT Motion Test ===")

    confirm = input(
        "실제 OMX2를 움직입니다. 실행할까요? (y/n): "
    ).strip().lower()

    if confirm != "y":
        print("실행 취소")
        return

    try:
        run_reject_motion()

    except KeyboardInterrupt:
        print("\n사용자가 동작을 중단했습니다.")

    except Exception as error:
        print(f"\n[ERROR] {error}")


if __name__ == "__main__":
    main()
