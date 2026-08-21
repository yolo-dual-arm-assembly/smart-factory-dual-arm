"""캘리브레이션 점의 로봇 좌표를 실측해 CSV에 채운다.

`click_calibration_points.py`가 만든 CSV에는 픽셀 좌표만 있고
`robot_x`, `robot_y`가 비어 있다. Homography를 구하려면 그 픽셀이
로봇 기준으로 어디인지 알아야 하는데, 이건 계산이 아니라 실측이다.

토크를 풀어 팔을 손으로 옮길 수 있게 한 뒤, 화면에 표시된 픽셀 위치에
그리퍼 끝을 맞추고 스페이스를 누르면 현재 관절각을 읽어 순기구학으로
XY를 계산해 채워 넣는다.

주의: 토크를 풀면 팔이 중력으로 내려앉는다. 시작 전에 팔을 받쳐라.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import pandas as pd

from common.camera import open_camera
from common.omx_controller import OmxConfig, OmxController, fk_5dof

CAPTURE_WIDTH = 640
CAPTURE_HEIGHT = 480

REQUIRED_COLUMNS = ["pixel_u", "pixel_v", "robot_x", "robot_y"]


def draw_guide(
    frame,
    target: tuple[int, int],
    index: int,
    total: int,
    measured: tuple[float, float, float] | None,
) -> None:
    """맞춰야 할 픽셀 위치와 현재 실측값을 화면에 그린다."""
    u, v = target

    cv2.drawMarker(
        frame,
        (u, v),
        (0, 0, 255),
        cv2.MARKER_CROSS,
        24,
        2,
    )
    cv2.circle(frame, (u, v), 16, (0, 0, 255), 2)

    lines = [
        f"point {index + 1}/{total}  pixel=({u}, {v})",
        "그리퍼 끝을 표시 위치에 맞추고 SPACE",
        "S=건너뛰기  U=직전 취소  Q=저장 후 종료",
    ]

    if measured is not None:
        x, y, z = measured
        lines.append(
            f"현재 FK: x={x:+.3f} y={y:+.3f} z={z:+.3f} m"
        )

    for row, text in enumerate(lines):
        cv2.putText(
            frame,
            text,
            (12, 26 + row * 24),
            cv2.FONT_HERSHEY_SIMPLEX,
            0.6,
            (0, 255, 255),
            2,
        )


def main(
    points_path: Path,
    camera_index: int,
    port: str | None,
) -> None:
    if not points_path.exists():
        raise FileNotFoundError(
            f"캘리브레이션 점 파일이 없습니다: {points_path}"
        )

    df = pd.read_csv(points_path)

    missing = set(REQUIRED_COLUMNS[:2]) - set(df.columns)

    if missing:
        raise ValueError(
            f"필요한 열이 없습니다: {sorted(missing)}"
        )

    for column in REQUIRED_COLUMNS[2:]:
        if column not in df.columns:
            df[column] = pd.NA

    config = OmxConfig(port=port) if port else OmxConfig()
    controller = OmxController(config)
    controller.connect()

    # 손으로 옮길 수 있도록 토크를 푼다.
    controller.disable_torque()
    print("토크를 풀었습니다. 팔을 손으로 옮길 수 있습니다.")

    capture = open_camera(camera_index, CAPTURE_WIDTH, CAPTURE_HEIGHT)

    index = 0
    total = len(df)

    try:
        while index < total:
            ok, frame = capture.read()

            if not ok:
                print("카메라 프레임 read 실패")
                break

            if frame.shape[:2] != (CAPTURE_HEIGHT, CAPTURE_WIDTH):
                frame = cv2.resize(
                    frame, (CAPTURE_WIDTH, CAPTURE_HEIGHT)
                )

            angles = controller.read_joint_state().angles
            measured = fk_5dof(angles)

            target = (
                int(df.at[index, "pixel_u"]),
                int(df.at[index, "pixel_v"]),
            )

            draw_guide(frame, target, index, total, measured)
            cv2.imshow("calibration", frame)

            key = cv2.waitKey(30) & 0xFF

            if key == ord(" "):
                x, y, _ = measured
                df.at[index, "robot_x"] = round(x, 5)
                df.at[index, "robot_y"] = round(y, 5)
                print(
                    f"point {index + 1}: pixel={target} → "
                    f"robot=({x:+.4f}, {y:+.4f})"
                )
                index += 1

            elif key == ord("s"):
                print(f"point {index + 1} 건너뜀")
                index += 1

            elif key == ord("u") and index > 0:
                index -= 1
                df.at[index, "robot_x"] = pd.NA
                df.at[index, "robot_y"] = pd.NA
                print(f"point {index + 1} 취소")

            elif key in (ord("q"), 27):
                break

    finally:
        capture.release()
        cv2.destroyAllWindows()

        if controller.is_connected:
            controller.disconnect()

        df.to_csv(points_path, index=False)
        print(f"\n저장 완료: {points_path}")

        filled = df[["robot_x", "robot_y"]].notna().all(axis=1).sum()
        print(f"실측 완료: {filled}/{total} 점")

        if filled < 4:
            print(
                "Homography 계산에는 최소 4점이 필요합니다. "
                "부족하면 다시 실행해 이어서 채우세요."
            )


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--points",
        type=Path,
        required=True,
        help="click_calibration_points.py가 만든 CSV",
    )

    parser.add_argument(
        "--camera",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--port",
        default=None,
        help="OMX 시리얼 포트. 생략하면 자동 선택",
    )

    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()

    main(
        points_path=arguments.points,
        camera_index=arguments.camera,
        port=arguments.port,
    )
