"""캘리브레이션에 쓸 픽셀 좌표를 클릭으로 모아 CSV에 저장한다.

`measure_calibration_points.py`가 이 CSV를 읽어 각 픽셀 위치에 대응하는
로봇 좌표를 실측해 채운다. 여기서는 화면에 보이는 지점을 순서대로
클릭해서 ``pixel_u``, ``pixel_v``만 기록한다.

화면 전체(작업 영역이 될 범위)에 고르게 퍼지도록 최소 9곳 이상 클릭하는
것을 권장한다 — 네 귀퉁이만 찍으면 중앙부 왜곡을 보정할 대응점이 없다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import cv2
import pandas as pd

from common.camera import open_camera

# vision_node가 실제로 쓰는 해상도와 반드시 맞춰야 한다 — 다르면 픽셀
# 좌표가 스케일이 어긋나 Homography 전체가 틀어진다.
CAPTURE_WIDTH = 1280
CAPTURE_HEIGHT = 720


def main(points_path: Path, camera_index: int) -> None:
    clicked: list[tuple[int, int]] = []

    def on_click(event: int, x: int, y: int, *_: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            clicked.append((x, y))
            print(f"point {len(clicked)}: pixel=({x}, {y})")

    capture = open_camera(camera_index, CAPTURE_WIDTH, CAPTURE_HEIGHT)
    cv2.namedWindow("click_calibration_points")
    cv2.setMouseCallback("click_calibration_points", on_click)

    print("작업 영역에 고르게 퍼지도록 9곳 이상 클릭하세요.")
    print("U=직전 취소  Q=저장 후 종료")

    try:
        while True:
            ok, frame = capture.read()
            if not ok:
                print("카메라 프레임 read 실패")
                break

            if frame.shape[:2] != (CAPTURE_HEIGHT, CAPTURE_WIDTH):
                frame = cv2.resize(frame, (CAPTURE_WIDTH, CAPTURE_HEIGHT))

            for idx, (u, v) in enumerate(clicked):
                cv2.circle(frame, (u, v), 8, (0, 255, 0), -1)
                cv2.putText(
                    frame, str(idx + 1), (u + 10, v),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 255, 0), 2,
                )
            cv2.putText(
                frame, f"{len(clicked)}점 클릭됨 (Q: 저장 후 종료)",
                (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.7, (0, 200, 255), 2,
            )
            cv2.imshow("click_calibration_points", frame)

            key = cv2.waitKey(30) & 0xFF
            if key == ord("u") and clicked:
                removed = clicked.pop()
                print(f"취소: pixel={removed}")
            elif key in (ord("q"), 27):
                break
    finally:
        capture.release()
        cv2.destroyAllWindows()

    if not clicked:
        print("클릭한 점이 없어 저장하지 않았습니다.")
        return

    df = pd.DataFrame(clicked, columns=["pixel_u", "pixel_v"])
    points_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(points_path, index=False)
    print(f"\n저장 완료: {points_path} ({len(clicked)}점)")
    if len(clicked) < 9:
        print("9점 미만입니다 — 정확도를 위해 다시 실행해 더 찍는 것을 권장합니다.")


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--points",
        type=Path,
        required=True,
        help="저장할 CSV 경로 (measure_calibration_points.py --points와 동일하게 지정)",
    )
    parser.add_argument("--camera", type=int, default=0)
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    main(points_path=arguments.points, camera_index=arguments.camera)
