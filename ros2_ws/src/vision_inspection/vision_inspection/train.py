import argparse
from pathlib import Path

from vision_inspection.training import (
    DEFAULT_BASE_MODEL,
    DEFAULT_DATA_CONFIG,
    DEFAULT_OUTPUT_DIR,
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
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help=(
            "학습 결과를 쌓을 상위 폴더 (기본: 레포의 runs/). "
            "Colab에서는 마운트한 Drive 경로를 주면 체크포인트가 Drive에 바로 쌓인다"
        ),
    )
    parser.add_argument(
        "--save-period",
        type=int,
        default=None,
        help="N epoch마다 epoch{N}.pt를 추가로 남긴다 (기본: last/best만 저장)",
    )
    parser.add_argument(
        "--device",
        default=None,
        help="학습 장치. 예: 0, cpu (기본: GPU가 있으면 자동으로 GPU)",
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help=(
            "중단된 학습을 이어서 한다. 체크포인트가 아직 없으면 그냥 처음부터 "
            "시작하므로 Colab 셀을 그대로 다시 실행해도 된다"
        ),
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
        output_dir=args.output_dir,
        save_period=args.save_period,
        device=args.device,
        resume=args.resume,
    )
    try:
        train(config)
    except ValueError as error:
        raise SystemExit(str(error)) from error


if __name__ == "__main__":
    train_model(parse_args())
