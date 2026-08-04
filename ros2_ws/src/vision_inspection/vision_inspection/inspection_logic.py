"""바구니 내부 공 개수와 불량을 세어 검사 결과를 만든다.

담당: 2번(YOLO). 이 모듈의 반환값 규격은 :class:`common.messages.InspectionResult`
하나로 고정한다. 통합 담당자는 이 결과만 보고 PASS/REJECT를 처리한다.
"""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Iterable

from common.constants import CONFIDENCE_THRESHOLD, OMX_MODEL_PATH
from common.messages import InspectionResult

# TODO(2번): 학습 데이터셋의 실제 클래스 이름으로 교체한다.
BALL_CLASS_NAMES = ("ball",)
DEFECT_CLASS_NAMES = ("defect", "bad_ball")


def count_detections(
    class_names: Iterable[str],
    ball_names: Iterable[str] = BALL_CLASS_NAMES,
    defect_names: Iterable[str] = DEFECT_CLASS_NAMES,
) -> InspectionResult:
    """탐지된 클래스 이름 목록을 검사 결과로 바꾼다.

    YOLO 없이도 검사 판정을 시험할 수 있도록 추론과 집계를 분리한다.
    """
    balls = set(ball_names)
    defects = set(defect_names)
    total = 0
    defect_count = 0
    for name in class_names:
        if name in defects:
            total += 1
            defect_count += 1
        elif name in balls:
            total += 1
    return InspectionResult.from_counts(total, defect_count)


def detected_class_names(result: Any) -> list[str]:
    """ultralytics 결과 하나에서 클래스 이름만 뽑는다."""
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    names = result.names
    return [names[int(box.cls)] for box in boxes]


def inspect_image(
    image_path: Path,
    model_path: Path = OMX_MODEL_PATH,
    confidence: float = CONFIDENCE_THRESHOLD,
) -> InspectionResult:
    """이미지 한 장을 검사해 결과를 반환한다."""
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    result = model(str(image_path), conf=confidence, verbose=False)[0]
    return count_detections(detected_class_names(result))


def main() -> None:
    parser = argparse.ArgumentParser(description="바구니 이미지를 검사합니다.")
    parser.add_argument("--source", type=Path, required=True, help="검사할 이미지")
    parser.add_argument(
        "--model", type=Path, default=OMX_MODEL_PATH, help="사용할 YOLO 가중치"
    )
    args = parser.parse_args()
    print(inspect_image(args.source, args.model).to_dict())


if __name__ == "__main__":
    main()
