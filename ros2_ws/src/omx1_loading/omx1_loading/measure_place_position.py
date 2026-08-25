"""바구니(놓는 위치)만 옮겨졌을 때 place_pos·place_z만 다시 잰다.

토크를 풀어 그리퍼를 손으로 새 바구니 위치에 맞춘 뒤 Enter를 누르면 현재
관절각으로 순기구학을 계산해 calibration.json의 place_pos·place_z만
갱신한다. pixel_pts/robot_pts(Homography, 픽셀↔로봇 매핑)는 건드리지 않으므로
카메라나 로봇 자체가 옮겨졌다면 이것만으로는 부족하고
click_calibration_points.py → measure_calibration_points.py →
build_calibration_from_csv.py로 전체를 다시 잡아야 한다.

주의: 토크를 풀면 팔이 중력으로 내려앉는다. 시작 전에 팔을 받쳐라.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from common.constants import OMX_CALIBRATION_PATH
from common.omx_controller import OmxConfig, OmxController, fk_5dof
from omx1_loading.coordinate_transform import OmxCalibration


def main(calibration_path: Path, port: str | None) -> None:
    cal = OmxCalibration.load(calibration_path)

    config = OmxConfig(port=port) if port else OmxConfig()
    controller = OmxController(config)
    controller.connect()
    controller.disable_torque()
    print("토크를 풀었습니다. 그리퍼를 새 바구니(놓을 자리)에 맞추세요.")

    try:
        while True:
            angles = controller.read_joint_state().angles
            x, y, z = fk_5dof(angles)
            answer = input(
                f"현재 FK: x={x:+.4f} y={y:+.4f} z={z:+.4f} m "
                "— 이 위치로 저장하려면 Enter, 다시 재려면 r+Enter, "
                "취소하려면 q+Enter: "
            ).strip().lower()
            if answer == "q":
                print("취소했습니다.")
                return
            if answer == "r":
                continue
            cal.place_pos = (round(x, 5), round(y, 5))
            cal.place_z = round(z, 5)
            break
    finally:
        controller.disconnect()

    cal.save(calibration_path)
    print(f"저장 완료: place_pos={cal.place_pos}, place_z={cal.place_z}")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--calibration", type=Path, default=OMX_CALIBRATION_PATH)
    parser.add_argument("--port", default=None, help="생략하면 자동 선택")
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    main(calibration_path=arguments.calibration, port=arguments.port)
