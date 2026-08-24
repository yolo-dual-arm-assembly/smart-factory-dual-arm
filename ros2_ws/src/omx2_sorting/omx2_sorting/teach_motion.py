import json
import math
from pathlib import Path

from common.omx_controller import OmxController

from omx2_sorting.motion_runner import CONFIG_DIR


def select_motion() -> tuple[str, Path]:
    while True:
        print("\n=== OMX2 Motion 선택 ===")
        print("1 : PASS")
        print("2 : REJECT")
        print("q : 종료")

        selection = input("\n선택: ").strip().lower()

        if selection == "1":
            return "PASS", CONFIG_DIR / "pass_waypoints.json"

        elif selection == "2":
            return "REJECT", CONFIG_DIR / "reject_waypoints.json"

        elif selection == "q":
            raise KeyboardInterrupt

        else:
            print("1, 2, q 중 하나를 입력하세요.")


def print_sequence(sequence):
    print("\n=== 현재 Sequence ===")

    if not sequence:
        print("저장된 동작이 없습니다.")
        return

    for index, step in enumerate(sequence, start=1):
        action = step["action"]

        if action == "move":
            print(f"{index}. MOVE")

        elif action == "gripper_close":
            print(f"{index}. GRIPPER CLOSE")

        elif action == "gripper_open":
            print(f"{index}. GRIPPER OPEN")


def main():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)

    try:
        motion_name, save_path = select_motion()
    except KeyboardInterrupt:
        print("\nTeaching 종료")
        return

    controller = OmxController()

    # 현재 Torque 상태를 프로그램에서도 기억
    torque_enabled = False

    try:
        controller.connect()

        # 시작할 때는 손으로 움직일 수 있도록 Torque OFF
        controller.disable_torque()
        torque_enabled = False

        print(f"\n=== OMX2 {motion_name} Teaching Mode ===")
        print("")
        print("r     : Torque OFF  → 손으로 자세 조절")
        print("t     : Torque ON   → 현재 자세 고정")
        print("ENTER : 현재 관절 자세 저장")
        print("")
        print("c     : Gripper Close 명령 추가")
        print("o     : Gripper Open 명령 추가")
        print("")
        print("p     : 현재 Sequence 확인")
        print("u     : 마지막 Step 삭제")
        print("s     : JSON 저장")
        print("q     : 종료")
        print("")
        print(f"저장 대상: {save_path}")
        print("")
        print("[현재 상태] Torque OFF")
        print("로봇팔을 손으로 원하는 자세로 움직이세요.")

        sequence = []

        while True:
            command = input("\n명령 입력: ").strip().lower()

            # ------------------------------------------
            # Torque OFF
            # ------------------------------------------
            if command == "r":
                controller.disable_torque()
                torque_enabled = False

                print("\n[Torque OFF]")
                print("로봇팔을 손으로 움직일 수 있습니다.")

            # ------------------------------------------
            # Torque ON
            # ------------------------------------------
            elif command == "t":
                controller.enable_torque()
                torque_enabled = True

                print("\n[Torque ON]")
                print("현재 자세를 고정합니다.")

            # ------------------------------------------
            # ENTER → 현재 자세 저장
            # ------------------------------------------
            elif command == "":
                if not torque_enabled:
                    print("\n[주의]")
                    print("현재 Torque가 OFF 상태입니다.")
                    print("t를 눌러 Torque ON 후 자세를 고정하고 저장하세요.")
                    continue

                state = controller.read_joint_state(strict=True)

                step = {
                    "action": "move",
                    "angles": state.angles,
                    "positions": state.positions,
                    "duration": 2.0,
                }

                sequence.append(step)

                print(
                    f"\n[Step {len(sequence)} 저장 완료: MOVE]"
                )

                for i, angle in enumerate(state.angles, start=1):
                    print(
                        f"J{i}: "
                        f"{math.degrees(angle):7.2f} deg "
                        f"({angle:.4f} rad)"
                    )

                print("DXL:", state.positions)

                print("\n다음 자세를 만들려면 r을 눌러 Torque OFF 하세요.")

            # ------------------------------------------
            # Gripper Close
            # ------------------------------------------
            elif command == "c":
                sequence.append(
                    {
                        "action": "gripper_close",
                        "duration": 1.0,
                    }
                )

                print(
                    f"[Step {len(sequence)} 저장 완료: "
                    "GRIPPER CLOSE]"
                )

            # ------------------------------------------
            # Gripper Open
            # ------------------------------------------
            elif command == "o":
                sequence.append(
                    {
                        "action": "gripper_open",
                        "duration": 1.0,
                    }
                )

                print(
                    f"[Step {len(sequence)} 저장 완료: "
                    "GRIPPER OPEN]"
                )

            # ------------------------------------------
            # Sequence 확인
            # ------------------------------------------
            elif command == "p":
                print_sequence(sequence)

            # ------------------------------------------
            # 마지막 Step 삭제
            # ------------------------------------------
            elif command == "u":
                if not sequence:
                    print("삭제할 Step이 없습니다.")
                    continue

                removed = sequence.pop()

                print(
                    f"마지막 Step 삭제 완료: "
                    f"{removed['action']}"
                )

            # ------------------------------------------
            # JSON 저장
            # ------------------------------------------
            elif command == "s":
                if not sequence:
                    print("저장된 Sequence가 없습니다.")
                    continue

                data = {
                    "motion": motion_name,
                    "step_count": len(sequence),
                    "sequence": sequence,
                }

                save_path.write_text(
                    json.dumps(data, indent=2),
                    encoding="utf-8",
                )

                print("\n=== 저장 완료 ===")
                print(f"파일: {save_path.resolve()}")
                print(f"Step 개수: {len(sequence)}")

            # ------------------------------------------
            # 종료
            # ------------------------------------------
            elif command == "q":
                print("Teaching 종료")
                break

            else:
                print(
                    "ENTER / r / t / c / o / "
                    "p / u / s / q 중 하나를 입력하세요."
                )

    except Exception as error:
        print(f"\n[ERROR] {error}")

    finally:
        controller.disconnect()


if __name__ == "__main__":
    main()