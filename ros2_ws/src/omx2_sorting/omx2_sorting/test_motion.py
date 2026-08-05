import json
import time
from pathlib import Path

from common.omx_controller import OmxController


# JSON 파일 위치
PACKAGE_ROOT = Path(__file__).resolve().parent.parent
CONFIG_DIR = PACKAGE_ROOT / "config"
PASS_PATH = CONFIG_DIR / "pass_waypoints.json"


def main():
    print("\n=== OMX2 PASS Motion Test ===")
    print(f"불러올 파일: {PASS_PATH}")

    # --------------------------------------------------
    # 1. JSON 읽기
    # --------------------------------------------------
    if not PASS_PATH.exists():
        print(f"\n[ERROR] JSON 파일이 없습니다.")
        print(PASS_PATH.resolve())
        return

    data = json.loads(
        PASS_PATH.read_text(encoding="utf-8")
    )

    sequence = data["sequence"]

    print(f"Motion: {data['motion']}")
    print(f"Step 개수: {len(sequence)}")

    # --------------------------------------------------
    # 2. 실행 여부 확인
    # --------------------------------------------------
    print("\n실행 순서:")

    for index, step in enumerate(sequence, start=1):
        print(f"{index}. {step['action']}")

    confirm = input(
        "\n실제 OMX2를 움직입니다. 실행할까요? (y/n): "
    ).strip().lower()

    if confirm != "y":
        print("실행 취소")
        return

    # --------------------------------------------------
    # 3. OMX 연결
    # --------------------------------------------------
    controller = OmxController()

    try:
        controller.connect()

        # 모터가 목표 위치를 유지하고 움직일 수 있도록 Torque ON
        controller.enable_torque()

        print("\n[OMX2 연결 완료]")
        print("3초 후 동작을 시작합니다...")

        time.sleep(3)

        # --------------------------------------------------
        # 4. Sequence 순서대로 실행
        # --------------------------------------------------
        for index, step in enumerate(sequence, start=1):

            action = step["action"]

            print(
                f"\n[Step {index}/{len(sequence)}] "
                f"{action}"
            )

            # ------------------------------
            # MOVE
            # ------------------------------
            if action == "move":

                angles = step["angles"]
                duration = step.get("duration", 2.0)

                controller.move_joints_smooth(
                    angles,
                    duration=duration,
                )

            # ------------------------------
            # GRIPPER CLOSE
            # ------------------------------
            elif action == "gripper_close":

                duration = step.get("duration", 1.0)

                controller.gripper_close(
                    duration=duration
                )

            # ------------------------------
            # GRIPPER OPEN
            # ------------------------------
            elif action == "gripper_open":

                duration = step.get("duration", 1.0)

                controller.gripper_open(
                    duration=duration
                )

            else:
                print(
                    f"[WARNING] 알 수 없는 action: "
                    f"{action}"
                )

            # 각 Step 사이 잠깐 대기
            time.sleep(0.3)

        print("\n=== PASS Motion 완료 ===")

    except KeyboardInterrupt:
        print("\n사용자가 테스트를 중단했습니다.")

    except Exception as error:
        print(f"\n[ERROR] {error}")

    finally:
        controller.disconnect()
        print("OMX2 연결 종료")


if __name__ == "__main__":
    main()