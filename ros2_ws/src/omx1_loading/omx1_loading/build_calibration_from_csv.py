"""measure_calibration_points.py가 채운 CSV로 calibration.json을 만든다.

pick_z·place_z·approach_z·place_pos는 픽셀↔로봇 매핑과 무관한 값이라
기존 calibration.json(있다면)에서 그대로 가져오고, 대응점(Homography)만
CSV 내용으로 새로 교체한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

from common.constants import OMX_CALIBRATION_PATH
from omx1_loading.coordinate_transform import OmxCalibration


def main(points_path: Path, out_path: Path) -> None:
    df = pd.read_csv(points_path)
    df = df.dropna(subset=["pixel_u", "pixel_v", "robot_x", "robot_y"])
    if len(df) < 4:
        raise ValueError(
            f"실측 완료된 점이 {len(df)}개뿐입니다. "
            "measure_calibration_points.py로 최소 4개(권장 9개 이상) 채우세요."
        )

    if out_path.exists():
        old = OmxCalibration.load(out_path)
        cal = OmxCalibration(
            pick_z=old.pick_z,
            place_z=old.place_z,
            approach_z=old.approach_z,
            place_pos=old.place_pos,
        )
        print(
            f"[Calibration] 기존 pick_z/place_z/approach_z/place_pos 유지: "
            f"{old.pick_z=}, {old.place_z=}, {old.approach_z=}, {old.place_pos=}"
        )
    else:
        cal = OmxCalibration()
        print("[Calibration] 기존 파일 없음 — pick_z/place_z/approach_z/place_pos 기본값 사용")

    for _, row in df.iterrows():
        cal.add_point(
            pixel=(row["pixel_u"], row["pixel_v"]),
            robot_xy=(row["robot_x"], row["robot_y"]),
        )

    cal.compute()
    err = cal.reprojection_error()
    print(f"재투영 오차: {err * 100:.3f} cm (대응점 {len(df)}개)")
    cal.save(out_path)


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--points",
        type=Path,
        required=True,
        help="measure_calibration_points.py로 채운 CSV",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=OMX_CALIBRATION_PATH,
        help="저장할 calibration.json 경로 (기본: 기존 위치, 덮어씀)",
    )
    return parser.parse_args()


if __name__ == "__main__":
    arguments = parse_arguments()
    main(points_path=arguments.points, out_path=arguments.out)
