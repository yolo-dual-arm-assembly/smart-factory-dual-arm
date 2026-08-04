"""YOLO 학습 설정 검증과 파인튜닝 실행."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from common.constants import DATASET_CONFIG_PATH, MODELS_DIR, PROJECT_DIR


DEFAULT_DATA_CONFIG = DATASET_CONFIG_PATH
DEFAULT_BASE_MODEL = MODELS_DIR / "yolov8n.pt"


@dataclass(frozen=True)
class TrainingConfig:
    data: Path = DEFAULT_DATA_CONFIG
    base_model: Path = DEFAULT_BASE_MODEL
    epochs: int = 50
    image_size: int = 640
    batch_size: int = 8
    run_name: str = "custom_detect"
    output_dir: Path = PROJECT_DIR / "runs"

    def validated(self) -> "TrainingConfig":
        """옵션을 검사하고 절대 경로 설정을 반환한다."""
        data = self.data.resolve()
        base_model = self.base_model.resolve()
        if not data.is_file():
            raise ValueError(f"데이터셋 정의 파일이 없습니다: {data}")
        if not base_model.is_file():
            raise ValueError(f"베이스 모델 파일이 없습니다: {base_model}")
        if self.epochs <= 0:
            raise ValueError("학습 epoch 수는 1 이상이어야 합니다.")
        if self.image_size <= 0:
            raise ValueError("학습 이미지 크기는 1 이상이어야 합니다.")
        if self.batch_size == 0 or self.batch_size < -1:
            raise ValueError("배치 크기는 -1 또는 1 이상이어야 합니다.")
        if not self.run_name.strip():
            raise ValueError("학습 결과 이름은 비워 둘 수 없습니다.")
        return TrainingConfig(
            data=data,
            base_model=base_model,
            epochs=self.epochs,
            image_size=self.image_size,
            batch_size=self.batch_size,
            run_name=self.run_name.strip(),
            output_dir=self.output_dir.resolve(),
        )


def train(
    config: TrainingConfig,
    model_factory: Callable[[Path], Any] | None = None,
) -> Any:
    """설정으로 YOLO 모델을 학습하고 결과를 반환한다."""
    validated = config.validated()
    if model_factory is None:
        from ultralytics import YOLO

        model_factory = YOLO

    model = model_factory(validated.base_model)
    return model.train(
        data=validated.data,
        epochs=validated.epochs,
        imgsz=validated.image_size,
        batch=validated.batch_size,
        project=validated.output_dir,
        name=validated.run_name,
    )
