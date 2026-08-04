"""카메라 픽셀 ↔ 로봇 좌표 Homography 캘리브레이션.

eye-to-hand 구성: 카메라가 고정 위치에서 테이블을 내려다보는 방식.
Z축은 테이블 높이로 고정한다.

사용 예::

    # 캘리브레이션 데이터 수집 및 저장
    cal = OmxCalibration(pick_z=0.015)
    cal.add_point(pixel=(320, 240), robot_xy=(0.20, 0.00))
    cal.add_point(pixel=(100, 100), robot_xy=(0.25, 0.10))
    cal.add_point(pixel=(540, 100), robot_xy=(0.25, -0.10))
    cal.add_point(pixel=(100, 380), robot_xy=(0.15, 0.10))
    cal.compute()
    cal.save("calibration.json")

    # 이후 사용
    cal = OmxCalibration.load("calibration.json")
    robot_xyz = cal.pixel_to_robot(cx, cy)
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import cv2
import numpy as np


FULL_FRAME_NEAR_X = 0.18
FULL_FRAME_FAR_X = 0.23
FULL_FRAME_LEFT_Y = 0.08
FULL_FRAME_RIGHT_Y = -0.08


def make_full_frame_calibration(width: int, height: int) -> "OmxCalibration":
    """전체 카메라 화면을 보수적인 OMX 작업 사각형에 대응시킨다.

    화면 위=로봇에서 먼 방향, 화면 아래=가까운 방향,
    화면 왼쪽=로봇 왼쪽 방향인 고정 카메라를 가정한다.
    """
    if width < 2 or height < 2:
        raise ValueError("카메라 영상 크기는 가로/세로 2픽셀 이상이어야 합니다.")

    calibration = OmxCalibration()
    right = float(width - 1)
    bottom = float(height - 1)
    calibration.add_point((0.0, 0.0), (FULL_FRAME_FAR_X, FULL_FRAME_LEFT_Y))
    calibration.add_point((right, 0.0), (FULL_FRAME_FAR_X, FULL_FRAME_RIGHT_Y))
    calibration.add_point(
        (right, bottom), (FULL_FRAME_NEAR_X, FULL_FRAME_RIGHT_Y)
    )
    calibration.add_point((0.0, bottom), (FULL_FRAME_NEAR_X, FULL_FRAME_LEFT_Y))
    calibration.compute()
    return calibration


@dataclass
class OmxCalibration:
    """픽셀 좌표 → 로봇 XYZ 좌표 변환 캘리브레이션.

    Attributes:
        pick_z: Pick 동작 시 Z 높이(미터). 테이블 표면 위 높이.
        _pixel_pts: 픽셀 좌표 목록 [(u, v), ...]
        _robot_pts: 대응 로봇 XY 좌표 목록 [(x, y), ...]
        _H: Homography 행렬 (3x3, None이면 아직 계산 안 됨)
    """

    pick_z: float = 0.015           # 물체 집을 때 Z 높이 (m)
    place_z: float = 0.030          # 물체 놓을 때 Z 높이 (m)
    approach_z: float = 0.080       # Pick 전 접근 높이 (m, 물체 위쪽)
    place_pos: tuple[float, float] = (0.15, -0.15)  # 내려놓을 로봇 XY (m)
    _pixel_pts: list[list[float]] = field(default_factory=list)
    _robot_pts: list[list[float]] = field(default_factory=list)
    _H: Optional[np.ndarray] = field(default=None, repr=False)

    # --- 캘리브레이션 데이터 수집 ---

    def add_point(
        self,
        pixel: tuple[float, float],
        robot_xy: tuple[float, float],
    ) -> None:
        """대응점 1개를 추가한다.

        Args:
            pixel: 카메라 이미지의 (u, v) 픽셀 좌표
            robot_xy: 로봇 베이스 기준 (x, y) 미터 좌표
        """
        self._pixel_pts.append(list(pixel))
        self._robot_pts.append(list(robot_xy))

    def remove_last_point(self) -> None:
        """가장 최근에 등록한 대응점을 제거한다."""
        if self._pixel_pts:
            self._pixel_pts.pop()
            self._robot_pts.pop()

    @property
    def pixel_points(self) -> tuple[tuple[float, float], ...]:
        """화면 표시용 픽셀 대응점의 읽기 전용 복사본을 반환한다."""
        return tuple((point[0], point[1]) for point in self._pixel_pts)

    @property
    def robot_points(self) -> tuple[tuple[float, float], ...]:
        """검증 및 화면 표시용 로봇 XY 대응점의 읽기 전용 복사본."""
        return tuple((point[0], point[1]) for point in self._robot_pts)

    @property
    def point_count(self) -> int:
        """현재 등록된 대응점 개수."""
        return len(self._pixel_pts)

    def compute(self) -> None:
        """Homography 행렬을 계산한다. 최소 4개 대응점이 필요하다."""
        if len(self._pixel_pts) < 4:
            raise ValueError(
                f"Homography 계산에 최소 4개 대응점 필요, 현재 {len(self._pixel_pts)}개"
            )
        src = np.float32(self._pixel_pts)
        dst = np.float32(self._robot_pts)
        H, status = cv2.findHomography(src, dst)
        if H is None:
            raise RuntimeError("Homography 행렬 계산 실패 (대응점 배치 확인 필요)")
        self._H = H
        n_inliers = int(status.sum()) if status is not None else len(self._pixel_pts)
        print(
            f"[Calibration] Homography 계산 완료 "
            f"(대응점 {len(self._pixel_pts)}개, 인라이어 {n_inliers}개)"
        )

    def pixel_to_robot(
        self, cx: float, cy: float
    ) -> tuple[float, float, float]:
        """픽셀 좌표를 로봇 XYZ(미터)로 변환한다.

        Args:
            cx: 이미지 X 픽셀 (bbox 중심)
            cy: 이미지 Y 픽셀 (bbox 중심)

        Returns:
            (robot_x, robot_y, pick_z) 튜플
        """
        if self._H is None:
            raise RuntimeError(
                "Homography 미계산. compute() 또는 load()를 먼저 호출하세요."
            )
        pt = np.array([[[cx, cy]]], dtype=np.float32)
        result = cv2.perspectiveTransform(pt, self._H)
        rx, ry = float(result[0, 0, 0]), float(result[0, 0, 1])
        return rx, ry, self.pick_z

    def reprojection_error(self) -> float:
        """재투영 오차 평균(미터)을 반환한다."""
        if self._H is None:
            raise RuntimeError("Homography 미계산")
        total = 0.0
        for pix, rob in zip(self._pixel_pts, self._robot_pts):
            pred = self.pixel_to_robot(pix[0], pix[1])
            err = math.sqrt((pred[0] - rob[0]) ** 2 + (pred[1] - rob[1]) ** 2)
            total += err
        return total / len(self._pixel_pts)

    # --- 저장 / 로드 ---

    def save(self, path: str | Path = "calibration.json") -> None:
        """캘리브레이션 데이터를 JSON 파일로 저장한다."""
        data = {
            "pick_z": self.pick_z,
            "place_z": self.place_z,
            "approach_z": self.approach_z,
            "place_pos": list(self.place_pos),
            "pixel_pts": self._pixel_pts,
            "robot_pts": self._robot_pts,
            "homography": self._H.tolist() if self._H is not None else None,
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"[Calibration] 저장됨: {path}")

    @classmethod
    def load(cls, path: str | Path = "calibration.json") -> "OmxCalibration":
        """JSON 파일에서 캘리브레이션 데이터를 불러온다."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        cal = cls(
            pick_z=data["pick_z"],
            place_z=data["place_z"],
            approach_z=data["approach_z"],
            place_pos=tuple(data["place_pos"]),  # type: ignore[arg-type]
        )
        cal._pixel_pts = data["pixel_pts"]
        cal._robot_pts = data["robot_pts"]
        if data["homography"] is not None:
            cal._H = np.float32(data["homography"])
        print(f"[Calibration] 불러옴: {path} ({len(cal._pixel_pts)}개 대응점)")
        return cal

    @property
    def is_ready(self) -> bool:
        """Homography가 계산된 상태인지 확인한다."""
        return self._H is not None


import math  # noqa: E402 (파일 하단 import 허용 — OmxCalibration 내부에서만 사용)
