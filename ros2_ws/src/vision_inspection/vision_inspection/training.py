"""YOLO 학습 설정 검증과 파인튜닝 실행."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from common.constants import DATASET_CONFIG_PATH, MODELS_DIR, PROJECT_DIR


DEFAULT_DATA_CONFIG = DATASET_CONFIG_PATH
DEFAULT_BASE_MODEL = MODELS_DIR / "yolov8n.pt"
DEFAULT_OUTPUT_DIR = PROJECT_DIR / "runs"


@dataclass(frozen=True)
class TrainingConfig:
    data: Path = DEFAULT_DATA_CONFIG
    base_model: Path = DEFAULT_BASE_MODEL
    epochs: int = 50
    image_size: int = 640
    batch_size: int = 8
    run_name: str = "custom_detect"
    output_dir: Path = DEFAULT_OUTPUT_DIR
    # 아래 셋은 Colab처럼 런타임이 예고 없이 끊기는 환경을 위한 선택 항목이다.
    # 기본값이면 ultralytics 기본 동작을 그대로 두고 인자를 넘기지 않는다.
    save_period: int | None = None
    device: str | None = None
    resume: bool = False

    def checkpoint_path(self) -> Path:
        """이어서 학습할 때 읽는 체크포인트 경로.

        ultralytics가 ``project/name/weights/last.pt``에 매 epoch 덮어쓴다.
        ``output_dir``을 Google Drive로 잡아 두면 이 파일이 Drive에 바로 쌓인다.
        """
        return self.output_dir / self.run_name / "weights" / "last.pt"

    def resuming(self) -> bool:
        """실제로 이어서 학습할 수 있는 상태인지.

        ``resume``을 켜 뒀어도 체크포인트가 아직 없으면 처음부터 시작한다. 덕분에
        Colab 셀 하나를 그대로 다시 실행해도 되고, 끊긴 뒤 재실행하면 이어진다.
        """
        return self.resume and self.checkpoint_path().is_file()

    def validated(self) -> "TrainingConfig":
        """옵션을 검사하고 절대 경로 설정을 반환한다."""
        data = self.data.resolve()
        base_model = self.base_model.resolve()
        output_dir = self.output_dir.resolve()
        run_name = self.run_name.strip()
        if not data.is_file():
            raise ValueError(f"데이터셋 정의 파일이 없습니다: {data}")
        if not run_name:
            raise ValueError("학습 결과 이름은 비워 둘 수 없습니다.")
        # 이어서 학습할 때는 체크포인트가 가중치를 들고 있으므로 베이스 모델이
        # 없어도 된다. 새 Colab 세션에서 베이스 가중치를 다시 받지 않아도 된다.
        resuming = (
            self.resume
            and (output_dir / run_name / "weights" / "last.pt").is_file()
        )
        if not resuming and not base_model.is_file():
            raise ValueError(f"베이스 모델 파일이 없습니다: {base_model}")
        if self.epochs <= 0:
            raise ValueError("학습 epoch 수는 1 이상이어야 합니다.")
        if self.image_size <= 0:
            raise ValueError("학습 이미지 크기는 1 이상이어야 합니다.")
        if self.batch_size == 0 or self.batch_size < -1:
            raise ValueError("배치 크기는 -1 또는 1 이상이어야 합니다.")
        if self.save_period is not None and self.save_period <= 0:
            raise ValueError("중간 저장 주기는 1 이상이어야 합니다.")
        return TrainingConfig(
            data=data,
            base_model=base_model,
            epochs=self.epochs,
            image_size=self.image_size,
            batch_size=self.batch_size,
            run_name=run_name,
            output_dir=output_dir,
            save_period=self.save_period,
            device=self.device,
            resume=self.resume,
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

    resuming = validated.resuming()
    # 이어서 학습할 때는 베이스 가중치가 아니라 체크포인트에서 모델을 만든다.
    # ultralytics가 optimizer 상태와 남은 epoch까지 체크포인트에서 복원한다.
    model = model_factory(
        validated.checkpoint_path() if resuming else validated.base_model
    )

    options: dict[str, Any] = {
        "data": validated.data,
        "epochs": validated.epochs,
        "imgsz": validated.image_size,
        "batch": validated.batch_size,
        "project": validated.output_dir,
        "name": validated.run_name,
    }
    # 선택 항목은 값이 있을 때만 넘겨 ultralytics 기본값을 덮어쓰지 않는다.
    if resuming:
        options["resume"] = True
    if validated.save_period is not None:
        options["save_period"] = validated.save_period
    if validated.device is not None:
        options["device"] = validated.device
    return model.train(**options)
