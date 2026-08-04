import argparse
from pathlib import Path

from vision_inspection.training import (
    DEFAULT_BASE_MODEL,
    DEFAULT_DATA_CONFIG,
    TrainingConfig,
    train,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="로컬 데이터셋으로 YOLO 모델을 파인튜닝합니다."
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_DATA_CONFIG,
        help="데이터셋 정의 yaml 경로 (기본: train_set/data.yaml)",
    )
    parser.add_argument(
        "--base-model",
        type=Path,
        default=DEFAULT_BASE_MODEL,
        help="베이스 가중치(.pt) 경로 (기본: yolov8n.pt)",
    )
    parser.add_argument("--epochs", type=int, default=50, help="학습 epoch 수")
    parser.add_argument("--imgsz", type=int, default=640, help="학습 이미지 크기")
    parser.add_argument("--batch", type=int, default=8, help="배치 크기")
    parser.add_argument(
        "--name", default="custom_detect", help="runs/ 하위 결과 폴더 이름"
    )
    return parser.parse_args()


def train_model(args: argparse.Namespace) -> None:
    """CLI 인자를 애플리케이션 학습 설정으로 변환해 실행한다."""
    config = TrainingConfig(
        data=args.data,
        base_model=args.base_model,
        epochs=args.epochs,
        image_size=args.imgsz,
        batch_size=args.batch,
        run_name=args.name,
    )
    try:
        train(config)
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    train_model(parse_args())
