"""바구니 내부를 촬영해 공 개수와 불량을 세고 PASS/REJECT를 판정한다.

담당: 2번(카메라 비전검사). 이 모듈의 반환값 규격은
:class:`common.messages.InspectionResult` 하나로 고정한다. 통합 담당자는 이
결과만 보고 분류를 지시한다.

판정 기준은 두 조각으로 나뉜다.

* 결함이 하나라도 있으면 REJECT — 공통 규격 ``InspectionResult.from_counts()``.
* 공 개수가 기준 수량과 다르면 REJECT — 이 모듈의 :func:`judge`.

개수 기준은 공통 규격에 없어서 이 패키지가 책임진다. 그래서 판정은 항상
:func:`judge`를 거쳐야 하고, 호출부가 ``from_counts()``를 직접 부르면 개수
불일치를 놓친다. 기대 개수는 ``InspectionResult``에 실리지 않으므로, 사람이
읽을 이유가 필요하면 :func:`verdict_reason`을 함께 쓴다.
"""
from __future__ import annotations

import argparse
from functools import lru_cache
from pathlib import Path
from typing import Any, Iterable

from common.constants import CONFIDENCE_THRESHOLD, OMX_MODEL_PATH, RobotState
from common.logger import get_logger
from common.messages import InspectionResult

from vision_inspection.class_scheme import (
    CLASS_SCHEME_PATH,
    ClassScheme,
    describe_scheme,
    load_class_scheme,
    load_target_count,
    warn_on_mismatch,
)

logger = get_logger(__name__)

# 카메라를 열자마자 찍으면 자동 노출·화이트밸런스가 잡히기 전이라 어둡거나
# 흐린 프레임이 나온다. 검사 전에 몇 장 버려 안정된 프레임을 쓴다.
WARMUP_FRAMES = 5


class _Unset:
    """'인자를 안 넘겼다'와 '개수 검사를 끄려고 None을 넘겼다'를 구분한다."""


UNSET = _Unset()


def resolve_target_count(target_count: int | None | _Unset) -> int | None:
    """기준 수량을 정한다. 안 넘기면 설정 파일 값을 쓴다.

    통합 제어기(5번)가 아직 기준 수량을 넘겨 주지 않아서, GUI처럼 인자 없이
    부르는 쪽도 설정값으로 개수 검사가 되도록 한다. 명시적으로 ``None``을
    넘기면 개수 검사를 끈다.
    """
    if isinstance(target_count, _Unset):
        return load_target_count()
    return target_count


def judge(
    total_count: int,
    defect_count: int,
    target_count: int | None | _Unset = UNSET,
) -> InspectionResult:
    """개수 일치와 무결함을 함께 보고 PASS/REJECT를 정한다.

    ``target_count``를 ``None``으로 주면 개수는 보지 않고 결함만 본다.
    아예 넘기지 않으면 설정 파일의 ``target_count``를 쓴다.
    """
    expected = resolve_target_count(target_count)
    result = InspectionResult.from_counts(total_count, defect_count)
    if expected is not None and total_count != expected:
        # 결함이 없어도 개수가 다르면 REJECT다. from_counts()는 개수를 모른다.
        return InspectionResult(total_count, defect_count, RobotState.REJECT)
    return result


def verdict_reason(
    result: InspectionResult, target_count: int | None | _Unset = UNSET
) -> str:
    """판정 이유를 사람이 읽는 한 줄로 만든다. GUI·로그용.

    기대 개수는 ``InspectionResult``에 실리지 않아서 여기서 다시 받는다.
    """
    expected = resolve_target_count(target_count)
    if result.is_pass:
        return f"정상 {result.total_count}개, 결함 없음"

    reasons = []
    if expected is not None and result.total_count != expected:
        reasons.append(f"개수 불일치 (기준 {expected}, 검출 {result.total_count})")
    if result.defect_count:
        # 오투입도 여기 합산되므로 둘을 한 낱말로 묶는다.
        reasons.append(f"불량/이물질 {result.defect_count}개")
    return ", ".join(reasons) or "판정 기준 불충족"


def count_detections(
    class_names: Iterable[str],
    scheme: ClassScheme | None = None,
    target_count: int | None | _Unset = UNSET,
) -> InspectionResult:
    """탐지된 클래스 이름 목록을 검사 결과로 바꾼다.

    YOLO 없이도 검사 판정을 시험할 수 있도록 추론과 집계를 분리한다.
    규칙에 없는 클래스(바구니, 사람 등)는 개수에 넣지 않는다.

    오투입(``foreign_names``)은 공이 아니므로 ``total_count``에는 넣지 않고
    ``defect_count``에 더한다. 공용 규격 ``InspectionResult``에 이물질 칸이
    따로 없어서, "합격을 막는 개수"로 함께 센다.
    """
    scheme = scheme or load_class_scheme()
    total = 0
    defect_count = 0
    foreign_count = 0
    for name in class_names:
        if scheme.is_foreign(name):
            foreign_count += 1
            continue
        if scheme.is_defect(name):
            defect_count += 1
        if scheme.is_ball(name):
            total += 1
    return judge(total, defect_count + foreign_count, target_count)


def detected_class_names(result: Any) -> list[str]:
    """ultralytics 결과 하나에서 클래스 이름만 뽑는다."""
    boxes = getattr(result, "boxes", None)
    if boxes is None:
        return []
    names = result.names
    return [names[int(box.cls)] for box in boxes]


@lru_cache(maxsize=2)
def load_model(model_path: Path = OMX_MODEL_PATH):
    """YOLO 가중치를 한 번만 읽는다.

    검사는 바구니마다 반복되므로 매번 로드하면 수 초씩 낭비된다.
    """
    from ultralytics import YOLO

    logger.info("YOLO 모델 로드: %s", model_path)
    return YOLO(str(model_path))


def model_class_names(model: Any) -> tuple[str, ...]:
    """모델이 아는 클래스 이름 목록. 설정 대조용."""
    names = getattr(model, "names", None) or {}
    if isinstance(names, dict):
        return tuple(str(name) for name in names.values())
    return tuple(str(name) for name in names)


def inspect_source(
    source: Any,
    model_path: Path = OMX_MODEL_PATH,
    confidence: float = CONFIDENCE_THRESHOLD,
    scheme: ClassScheme | None = None,
    target_count: int | None | _Unset = UNSET,
) -> InspectionResult:
    """이미지 경로든 이미 읽은 프레임이든 한 장을 검사한다."""
    scheme = scheme or load_class_scheme()
    model = load_model(model_path)
    warn_on_mismatch(scheme, model_class_names(model))

    result = model(source, conf=confidence, verbose=False)[0]
    names = detected_class_names(result)
    logger.info("검출 클래스: %s (%s)", names, describe_scheme(scheme))
    return count_detections(names, scheme, target_count)


def inspect_image(
    image_path: Path,
    model_path: Path = OMX_MODEL_PATH,
    confidence: float = CONFIDENCE_THRESHOLD,
    scheme: ClassScheme | None = None,
    target_count: int | None | _Unset = UNSET,
) -> InspectionResult:
    """이미지 한 장을 검사해 결과를 반환한다."""
    return inspect_source(
        str(image_path), model_path, confidence, scheme, target_count
    )


def capture_frame(
    camera_index: int | None = None, warmup_frames: int = WARMUP_FRAMES
) -> Any:
    """바구니를 찍어 프레임 하나(BGR ndarray)를 돌려준다.

    ``camera_index``가 ``None``이면 운영체제별 선호 카메라를 자동으로 고른다.
    """
    from common.camera import open_camera, open_preferred_camera

    if camera_index is None:
        capture, camera_index = open_preferred_camera()
    else:
        capture = open_camera(camera_index)

    try:
        frame = None
        for _ in range(max(warmup_frames, 1)):
            grabbed, latest = capture.read()
            if grabbed:
                frame = latest
        if frame is None:
            raise RuntimeError(
                f"카메라 {camera_index}번이 프레임을 반환하지 않습니다."
            )
        return frame
    finally:
        capture.release()


def inspect_basket(
    target_count: int | None | _Unset = UNSET,
    camera_index: int | None = None,
    model_path: Path = OMX_MODEL_PATH,
    confidence: float = CONFIDENCE_THRESHOLD,
    scheme: ClassScheme | None = None,
) -> InspectionResult:
    """카메라로 바구니를 촬영해 검사한다. 통합 담당자가 부르는 진입점."""
    frame = capture_frame(camera_index)
    return inspect_source(frame, model_path, confidence, scheme, target_count)


def main() -> None:
    parser = argparse.ArgumentParser(description="바구니를 검사합니다.")
    parser.add_argument(
        "--source",
        type=Path,
        help="검사할 이미지. 생략하면 카메라로 촬영한다.",
    )
    parser.add_argument(
        "--camera", type=int, default=None, help="사용할 카메라 번호"
    )
    parser.add_argument(
        "--target-count",
        type=int,
        default=None,
        help="바구니에 있어야 할 공 개수. 생략하면 설정 파일의 값을 쓴다.",
    )
    parser.add_argument(
        "--model", type=Path, default=OMX_MODEL_PATH, help="사용할 YOLO 가중치"
    )
    parser.add_argument(
        "--conf",
        type=float,
        default=CONFIDENCE_THRESHOLD,
        help="추론 신뢰도 임계값",
    )
    parser.add_argument(
        "--scheme",
        type=Path,
        default=CLASS_SCHEME_PATH,
        help="클래스 규칙 파일. 공용 설정을 고치지 않고 시험할 때 쓴다.",
    )
    args = parser.parse_args()
    scheme = load_class_scheme(args.scheme)
    # --scheme으로 다른 파일을 줬으면 기준 수량도 그 파일에서 읽어야 한다.
    target_count = (
        load_target_count(args.scheme)
        if args.target_count is None
        else args.target_count
    )

    if args.source is not None:
        result = inspect_image(
            args.source, args.model, args.conf, scheme, target_count
        )
    else:
        result = inspect_basket(
            target_count, args.camera, args.model, args.conf, scheme
        )

    print(result.to_dict())
    print(verdict_reason(result, target_count))


if __name__ == "__main__":
    main()
