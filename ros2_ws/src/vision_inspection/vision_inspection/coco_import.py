"""COCO 데이터셋을 ball/others 2클래스 학습 세션으로 변환.

COCO val2017 이미지 일부를 샘플링해 sports ball은 ball(0)로, 나머지 모든
물체는 others(1)로 재매핑한 라벨을 만들고, 기존 촬영 세션과 같은
``train_set/coco_others/{images,labels}/train`` 구조로 복사한다. 학습에 안
보인 물체를 others로 잡는 일반화 성능(other_val 지표)을 올리는 용도다.

기본 사용(레포 루트에서 실행):
    python -m vision_inspection.coco_import                       # val2017에서 800장
    python -m vision_inspection.coco_import --count 1500 --force  # 더 많이 + 재생성

1회 준비 — COCO val2017을 받아 둔다(약 1GB, train_set/*라 git이 무시한다):
    mkdir -p train_set/coco_src && cd train_set/coco_src
    wget http://images.cocodataset.org/zips/val2017.zip && unzip val2017.zip
    wget http://images.cocodataset.org/annotations/annotations_trainval2017.zip \
        && unzip annotations_trainval2017.zip

만든 세션은 data.yaml의 train 목록에만 넣는다. val 추출은 일부러 하지
않는다 — COCO는 촬영 도메인이 달라 val 지표를 왜곡하고, 일반화 측정은
other_val 세션이 담당한다.
"""
from __future__ import annotations

import argparse
import json
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Sequence

from common.constants import PROJECT_DIR


TRAIN_SET_DIR = PROJECT_DIR / "train_set"
DEFAULT_COCO_DIR = TRAIN_SET_DIR / "coco_src"
DEFAULT_ANNOTATIONS = DEFAULT_COCO_DIR / "annotations" / "instances_val2017.json"
DEFAULT_IMAGES_DIR = DEFAULT_COCO_DIR / "val2017"
DEFAULT_OUTPUT_DIR = TRAIN_SET_DIR / "coco_others"

# val2017은 이미지당 평균 ~7개 물체다. 800장이면 others 인스턴스가 약 5,700개
# 추가돼 촬영분(약 2,600개)과 합쳐 ball(약 6,200개)을 조금 넘는 수준이 된다.
# 풀 전체(약 4,900장)까지 올릴 수는 있지만 others가 ball을 크게 압도하게 된다.
DEFAULT_COUNT = 800
DEFAULT_SEED = 0

# COCO는 공을 'ball'이 아니라 'sports ball'이라고 부른다. 매핑 결과 클래스
# 번호는 data.yaml의 names와 글자 그대로 일치해야 한다.
BALL_CATEGORY_NAME = "sports ball"
BALL_CLASS_ID = 0
OTHERS_CLASS_ID = 1

_DOWNLOAD_GUIDE = (
    "COCO val2017을 먼저 받아 두세요(레포 루트에서):\n"
    "  mkdir -p train_set/coco_src && cd train_set/coco_src\n"
    "  wget http://images.cocodataset.org/zips/val2017.zip && unzip val2017.zip\n"
    "  wget http://images.cocodataset.org/annotations/annotations_trainval2017.zip"
    " && unzip annotations_trainval2017.zip"
)


@dataclass(frozen=True)
class CocoImportConfig:
    annotations: Path = DEFAULT_ANNOTATIONS
    images_dir: Path = DEFAULT_IMAGES_DIR
    output_dir: Path = DEFAULT_OUTPUT_DIR
    count: int = DEFAULT_COUNT
    seed: int = DEFAULT_SEED
    ball_category: str = BALL_CATEGORY_NAME
    force: bool = False

    def validated(self) -> "CocoImportConfig":
        """옵션을 검사하고 절대 경로 설정을 반환한다."""
        annotations = self.annotations.resolve()
        images_dir = self.images_dir.resolve()
        output_dir = self.output_dir.resolve()
        if not annotations.is_file():
            raise ValueError(
                f"COCO 어노테이션 파일이 없습니다: {annotations}\n{_DOWNLOAD_GUIDE}"
            )
        if not images_dir.is_dir():
            raise ValueError(
                f"COCO 이미지 폴더가 없습니다: {images_dir}\n{_DOWNLOAD_GUIDE}"
            )
        if self.count <= 0:
            raise ValueError("샘플링 이미지 수는 1 이상이어야 합니다.")
        if not self.ball_category.strip():
            raise ValueError("ball로 매핑할 카테고리 이름은 비워 둘 수 없습니다.")
        if not self.force and output_dir.is_dir() and any(output_dir.iterdir()):
            raise ValueError(
                f"출력 폴더가 비어 있지 않습니다(--force로 대체): {output_dir}"
            )
        return CocoImportConfig(
            annotations=annotations,
            images_dir=images_dir,
            output_dir=output_dir,
            count=self.count,
            seed=self.seed,
            ball_category=self.ball_category,
            force=self.force,
        )


@dataclass(frozen=True)
class ImageRecord:
    """이미지 한 장과 거기 딸린 YOLO 라벨 줄들."""

    image_id: int
    file_name: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class ConversionResult:
    """변환된 이미지 목록과 스킵 집계."""

    records: tuple[ImageRecord, ...]
    skipped_crowd: int
    skipped_unlabeled_images: int


@dataclass(frozen=True)
class ImportSummary:
    """세션 생성 결과 요약. CLI가 그대로 출력한다."""

    images: int
    ball_instances: int
    others_instances: int
    skipped_crowd: int
    skipped_unlabeled_images: int


def yolo_line(
    bbox: Sequence[float], width: int, height: int, class_id: int
) -> str | None:
    """COCO 픽셀 bbox([x, y, w, h], 좌상단 기준)를 YOLO 라벨 한 줄로 바꾼다.

    이미지 경계 밖은 잘라내고, 잘라낸 뒤 넓이가 없으면(퇴화 박스) None을
    돌려줘 호출자가 스킵하게 한다.
    """
    if width <= 0 or height <= 0:
        return None
    x, y, w, h = bbox
    left = min(max(x, 0.0), float(width))
    top = min(max(y, 0.0), float(height))
    right = min(max(x + w, 0.0), float(width))
    bottom = min(max(y + h, 0.0), float(height))
    if right <= left or bottom <= top:
        return None
    center_x = (left + right) / 2 / width
    center_y = (top + bottom) / 2 / height
    norm_w = (right - left) / width
    norm_h = (bottom - top) / height
    return f"{class_id} {center_x:.6f} {center_y:.6f} {norm_w:.6f} {norm_h:.6f}"


def convert_instances(data: dict[str, Any], ball_category: str) -> ConversionResult:
    """COCO instances JSON을 이미지별 YOLO 라벨로 변환한다.

    ball_category(기본 'sports ball')는 ball, 나머지 카테고리는 전부 others가
    된다. iscrowd 어노테이션과, 변환 후 라벨이 한 줄도 없는 이미지는
    제외한다 — 배경(negative)은 도메인이 맞는 no_ball 세션이 이미 담당한다.
    """
    ball_ids = {
        category["id"]
        for category in data.get("categories", [])
        if category.get("name") == ball_category
    }
    if not ball_ids:
        raise ValueError(f"COCO 카테고리에 '{ball_category}'가 없습니다.")
    images = {
        image["id"]: (image["file_name"], image["width"], image["height"])
        for image in data.get("images", [])
    }
    lines_by_image: dict[int, list[str]] = {}
    skipped_crowd = 0
    for annotation in data.get("annotations", []):
        if annotation.get("iscrowd"):
            skipped_crowd += 1
            continue
        image_id = annotation["image_id"]
        if image_id not in images:
            continue
        _, width, height = images[image_id]
        class_id = (
            BALL_CLASS_ID
            if annotation["category_id"] in ball_ids
            else OTHERS_CLASS_ID
        )
        line = yolo_line(annotation["bbox"], width, height, class_id)
        if line is None:
            continue
        lines_by_image.setdefault(image_id, []).append(line)
    records = tuple(
        ImageRecord(image_id=image_id, file_name=images[image_id][0], lines=tuple(lines))
        for image_id, lines in sorted(lines_by_image.items())
    )
    return ConversionResult(
        records=records,
        skipped_crowd=skipped_crowd,
        skipped_unlabeled_images=len(images) - len(records),
    )


def sample_records(
    records: Sequence[ImageRecord], count: int, seed: int
) -> list[ImageRecord]:
    """라벨이 있는 이미지 풀에서 count장을 결정적으로 샘플링한다."""
    if count > len(records):
        raise ValueError(
            f"샘플링 이미지 수({count})가 라벨 있는 이미지 수({len(records)})보다"
            " 많습니다."
        )
    picked = random.Random(seed).sample(list(records), count)
    return sorted(picked, key=lambda record: record.image_id)


def write_session(
    records: Sequence[ImageRecord],
    images_dir: Path,
    output_dir: Path,
    copy: Callable[[Path, Path], object] = shutil.copy2,
) -> None:
    """기존 촬영 세션과 같은 images/train + labels/train 구조로 쓴다."""
    images_out = output_dir / "images" / "train"
    labels_out = output_dir / "labels" / "train"
    images_out.mkdir(parents=True, exist_ok=True)
    labels_out.mkdir(parents=True, exist_ok=True)
    for record in records:
        source = images_dir / record.file_name
        if not source.is_file():
            raise ValueError(
                f"COCO 이미지 파일이 없습니다(압축을 다시 푸세요): {source}"
            )
        copy(source, images_out / record.file_name)
        label_path = labels_out / (Path(record.file_name).stem + ".txt")
        label_path.write_text("\n".join(record.lines) + "\n", encoding="utf-8")


def import_coco(
    config: CocoImportConfig,
    copy: Callable[[Path, Path], object] = shutil.copy2,
) -> ImportSummary:
    """설정대로 COCO를 변환·샘플링해 세션 폴더를 만들고 요약을 돌려준다."""
    validated = config.validated()
    data = json.loads(validated.annotations.read_text(encoding="utf-8"))
    converted = convert_instances(data, validated.ball_category)
    sampled = sample_records(converted.records, validated.count, validated.seed)
    # 변환·샘플링이 다 성공한 뒤에야 기존 세션을 지운다.
    if validated.force and validated.output_dir.exists():
        shutil.rmtree(validated.output_dir)
    write_session(sampled, validated.images_dir, validated.output_dir, copy=copy)
    ball_instances = sum(
        1
        for record in sampled
        for line in record.lines
        if line.split(maxsplit=1)[0] == str(BALL_CLASS_ID)
    )
    total_instances = sum(len(record.lines) for record in sampled)
    return ImportSummary(
        images=len(sampled),
        ball_instances=ball_instances,
        others_instances=total_instances - ball_instances,
        skipped_crowd=converted.skipped_crowd,
        skipped_unlabeled_images=converted.skipped_unlabeled_images,
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="COCO 데이터셋을 ball/others 2클래스 학습 세션으로 변환합니다."
    )
    parser.add_argument(
        "--annotations",
        type=Path,
        default=DEFAULT_ANNOTATIONS,
        help="COCO instances JSON 경로",
    )
    parser.add_argument(
        "--images-dir",
        type=Path,
        default=DEFAULT_IMAGES_DIR,
        help="COCO 이미지 폴더",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="만들 세션 폴더",
    )
    parser.add_argument(
        "--count", type=int, default=DEFAULT_COUNT, help="샘플링할 이미지 수"
    )
    parser.add_argument(
        "--seed", type=int, default=DEFAULT_SEED, help="샘플링 시드(재현용)"
    )
    parser.add_argument(
        "--ball-category",
        default=BALL_CATEGORY_NAME,
        help="ball로 매핑할 COCO 카테고리 이름",
    )
    parser.add_argument(
        "--force", action="store_true", help="기존 출력 폴더를 지우고 다시 만든다"
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = CocoImportConfig(
        annotations=args.annotations,
        images_dir=args.images_dir,
        output_dir=args.output_dir,
        count=args.count,
        seed=args.seed,
        ball_category=args.ball_category,
        force=args.force,
    )
    try:
        summary = import_coco(config)
    except ValueError as error:
        raise SystemExit(str(error)) from error
    print(
        f"images={summary.images} ball={summary.ball_instances}"
        f" others={summary.others_instances} skipped_crowd={summary.skipped_crowd}"
        f" skipped_unlabeled={summary.skipped_unlabeled_images}"
    )
    print("data.yaml의 train 목록에 coco_others 항목이 있는지 확인하세요.")


if __name__ == "__main__":
    main()
