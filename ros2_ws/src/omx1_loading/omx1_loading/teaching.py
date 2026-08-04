"""카메라 Mouse 위치와 사용자가 교시한 OMX 관절 자세의 대응 데이터."""
from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

from common.omx_controller import JOINT_LIMITS, angle_to_dxl


MIN_TEACHING_POINTS = 4
REPLACE_PIXEL_DISTANCE = 5.0


@dataclass(frozen=True)
class TeachingPoint:
    pixel: tuple[float, float]
    angles: tuple[float, float, float, float, float]
    positions: tuple[int, int, int, int, int]


class OmxTeachingDataset:
    """교시점 저장과 안전한 관절 공간 보간을 담당한다."""

    def __init__(self, frame_size: tuple[int, int] | None = None) -> None:
        self.frame_size = frame_size
        self.points: list[TeachingPoint] = []

    @property
    def point_count(self) -> int:
        return len(self.points)

    @property
    def is_ready(self) -> bool:
        if self.point_count < MIN_TEACHING_POINTS:
            return False
        hull = cv2.convexHull(self._pixel_array())
        return abs(cv2.contourArea(hull)) > 1.0

    def add_point(
        self,
        pixel: tuple[float, float],
        angles: list[float] | tuple[float, ...],
        frame_size: tuple[int, int],
        positions: list[int] | tuple[int, ...] | None = None,
    ) -> None:
        if len(angles) != 5:
            raise ValueError("교시 자세에는 5개 관절각이 필요합니다.")
        width, height = frame_size
        if width < 2 or height < 2:
            raise ValueError("잘못된 카메라 영상 크기입니다.")
        if self.frame_size is None:
            self.frame_size = frame_size
        elif self.frame_size != frame_size:
            raise ValueError(
                f"카메라 해상도가 다릅니다: {frame_size} != {self.frame_size}"
            )

        px, py = float(pixel[0]), float(pixel[1])
        if not (0 <= px < width and 0 <= py < height):
            raise ValueError("Mouse 픽셀 좌표가 영상 범위 밖입니다.")
        angle_tuple = tuple(float(value) for value in angles)
        if positions is None:
            position_tuple = tuple(angle_to_dxl(angle) for angle in angle_tuple)
        else:
            if len(positions) != 5:
                raise ValueError("교시 자세에는 5개 모터 위치값이 필요합니다.")
            position_tuple = tuple(int(value) for value in positions)
        for index, (angle, (lower, upper)) in enumerate(
            zip(angle_tuple, JOINT_LIMITS), start=1
        ):
            if not lower <= angle <= upper:
                raise ValueError(
                    f"J{index} 교시각이 허용 범위 밖입니다: "
                    f"{math.degrees(angle):.1f}°"
                )

        point = TeachingPoint(  # type: ignore[arg-type]
            (px, py), angle_tuple, position_tuple
        )
        for index, existing in enumerate(self.points):
            if math.dist(existing.pixel, point.pixel) <= REPLACE_PIXEL_DISTANCE:
                self.points[index] = point
                return
        self.points.append(point)

    def remove_last_point(self) -> None:
        if self.points:
            self.points.pop()

    def contains_pixel(self, pixel: tuple[float, float]) -> bool:
        """픽셀이 교시점의 볼록 껍질 내부인지 확인한다."""
        if not self.is_ready:
            return False
        hull = cv2.convexHull(self._pixel_array())
        return cv2.pointPolygonTest(hull, pixel, False) >= 0

    def predict(self, pixel: tuple[float, float], neighbors: int = 4) -> list[float]:
        """가까운 교시 자세들을 역거리 가중 평균해 목표 관절각을 구한다."""
        if not self.is_ready:
            raise RuntimeError(f"교시점이 최소 {MIN_TEACHING_POINTS}개 필요합니다.")
        if not self.contains_pixel(pixel):
            raise ValueError("Mouse가 교시된 화면 영역 밖에 있습니다.")
        if self.frame_size is None:
            raise RuntimeError("교시 데이터에 카메라 해상도가 없습니다.")

        width, height = self.frame_size
        px, py = pixel
        ranked: list[tuple[float, TeachingPoint]] = []
        for point in self.points:
            dx = (point.pixel[0] - px) / width
            dy = (point.pixel[1] - py) / height
            distance = math.hypot(dx, dy)
            if distance < 1e-9:
                return list(point.angles)
            ranked.append((distance, point))

        nearest = sorted(ranked, key=lambda item: item[0])[: max(1, neighbors)]
        weights = [1.0 / (distance * distance) for distance, _ in nearest]
        weight_sum = sum(weights)
        return [
            sum(weight * point.angles[joint] for weight, (_, point) in zip(weights, nearest))
            / weight_sum
            for joint in range(5)
        ]

    def save(self, path: str | Path) -> None:
        if self.frame_size is None:
            raise RuntimeError("저장할 교시점이 없습니다.")
        data = {
            "version": 1,
            "frame_size": list(self.frame_size),
            "points": [asdict(point) for point in self.points],
        }
        Path(path).write_text(json.dumps(data, indent=2), encoding="utf-8")

    @classmethod
    def load(cls, path: str | Path) -> "OmxTeachingDataset":
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if data.get("version") != 1:
            raise ValueError("지원하지 않는 OMX 교시 데이터 버전입니다.")
        dataset = cls(tuple(data["frame_size"]))
        for item in data["points"]:
            dataset.add_point(
                tuple(item["pixel"]),
                item["angles"],
                dataset.frame_size,  # type: ignore[arg-type]
                item.get("positions"),
            )
        return dataset

    def _pixel_array(self) -> np.ndarray:
        return np.asarray([point.pixel for point in self.points], dtype=np.float32)
