"""webcam.py와 camera_feed.py의 캡처 루프가 공유하는 순수 계산.

두 파일 다 카메라 프레임을 읽으며 FPS를 지수이동평균(EMA)으로 갱신하고, YOLO
결과를 프레임에 그려 박스 개수를 센다. 스레드·Tk·카메라 장치를 전혀 건드리지
않는 순수 계산이라 여기 모아 두면 하드웨어 없이 그대로 테스트할 수 있다.
"""
from __future__ import annotations

from typing import Any


def update_fps(previous_fps: float, elapsed: float) -> float:
    """지수이동평균(EMA)으로 FPS를 갱신한다.

    ``elapsed``가 0 이하일 때 어떻게 할지는 호출부 책임이다 — 캡처 루프는
    호출 전에 걸러 내고, 추론 루프는 그대로 부른다(기존 동작을 그대로 유지).
    """
    return 0.9 * previous_fps + 0.1 / elapsed if previous_fps else 1.0 / elapsed


def annotate_and_count(result: Any, frame: Any) -> tuple[Any, int]:
    """YOLO 결과를 프레임에 그리고 박스 개수를 센다.

    ``result.plot()``은 넘겨준 이미지에 직접 그리므로, 원본 프레임을
    보호하려면 복사본을 넘겨야 한다.
    """
    annotated = result.plot(img=frame.copy())
    count = 0 if result.boxes is None else len(result.boxes)
    return annotated, count
