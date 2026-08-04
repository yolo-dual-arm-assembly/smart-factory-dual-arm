from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ultralytics.utils.downloads import attempt_download_asset

from common.constants import MODELS_DIR


@dataclass(frozen=True)
class ModelSpec:
    label: str
    filename: str
    downloadable: bool = True


MODEL_SPECS: tuple[ModelSpec, ...] = (
    ModelSpec(
        "Robot Custom (POC · 학습된 로봇 객체 탐지 모델)",
        "best.pt",
        downloadable=False,
    ),
    ModelSpec(
        "YOLOv8n (Low · 가장 가벼움 · 빠른 객체 탐지/저사양 CPU에 적합)",
        "yolov8n.pt",
    ),
    ModelSpec(
        "YOLOv8m (Advanced · 정확도와 속도의 균형 · 일반 객체 탐지에 적합)",
        "yolov8m.pt",
    ),
    ModelSpec(
        "YOLO11m-seg (Advanced · 객체 윤곽 마스크 · 정밀 영역 분할에 특화)",
        "yolo11m-seg.pt",
    ),
)
SPECS_BY_LABEL = {spec.label: spec for spec in MODEL_SPECS}
MODEL_FILENAMES = tuple(spec.filename for spec in MODEL_SPECS)
LOCAL_MODEL_FILENAMES = {spec.filename for spec in MODEL_SPECS if not spec.downloadable}
DOWNLOADABLE_MODEL_FILENAMES = tuple(
    spec.filename for spec in MODEL_SPECS if spec.downloadable
)
DEFAULT_MODEL_FILENAME = "yolo11m-seg.pt"


def available_model_specs(models_dir: Path | None = None) -> list[ModelSpec]:
    """Return specs to show in the UI; local-only models need their weight file."""
    root = MODELS_DIR if models_dir is None else models_dir
    return [
        spec
        for spec in MODEL_SPECS
        if spec.downloadable or (root / spec.filename).is_file()
    ]


def missing_model_paths(models_dir: Path | None = None) -> list[Path]:
    """Return model paths that must be downloaded before analysis."""
    root = MODELS_DIR if models_dir is None else models_dir
    return [
        root / filename
        for filename in DOWNLOADABLE_MODEL_FILENAMES
        if not (root / filename).is_file()
    ]


def download_model(model_path: Path) -> Path:
    """Download one official Ultralytics model to its project path."""
    # 새로 받은 저장소에는 models/ 폴더가 비어 있거나 아예 없다.
    model_path.parent.mkdir(parents=True, exist_ok=True)
    downloaded_path = Path(attempt_download_asset(model_path))
    if not downloaded_path.is_file():
        raise FileNotFoundError(f"모델 다운로드에 실패했습니다: {model_path.name}")
    return downloaded_path
