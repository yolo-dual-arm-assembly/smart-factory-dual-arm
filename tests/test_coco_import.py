"""coco_import의 변환·샘플링·세션 생성 로직 테스트."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from vision_inspection.coco_import import (
    BALL_CLASS_ID,
    OTHERS_CLASS_ID,
    CocoImportConfig,
    ImageRecord,
    convert_instances,
    import_coco,
    sample_records,
    write_session,
    yolo_line,
)


def make_coco_data() -> dict:
    """sports ball 한 개, person 한 명, crowd 하나, 빈 이미지 하나짜리 최소 COCO."""
    return {
        "categories": [
            {"id": 1, "name": "person"},
            {"id": 37, "name": "sports ball"},
        ],
        "images": [
            {"id": 10, "file_name": "000000000010.jpg", "width": 100, "height": 200},
            {"id": 20, "file_name": "000000000020.jpg", "width": 100, "height": 100},
            {"id": 30, "file_name": "000000000030.jpg", "width": 100, "height": 100},
        ],
        "annotations": [
            {"image_id": 10, "category_id": 37, "bbox": [10, 20, 30, 40], "iscrowd": 0},
            {"image_id": 10, "category_id": 1, "bbox": [0, 0, 50, 50], "iscrowd": 0},
            # 20번은 crowd 하나뿐이라 라벨 0줄, 30번은 어노테이션 자체가 없다.
            {"image_id": 20, "category_id": 1, "bbox": [10, 10, 20, 20], "iscrowd": 1},
        ],
    }


def make_source_tree(tmp_path: Path, data: dict | None = None) -> CocoImportConfig:
    """가짜 COCO 원본 트리를 만들고 그걸 가리키는 설정을 돌려준다."""
    data = make_coco_data() if data is None else data
    annotations = tmp_path / "instances.json"
    annotations.write_text(json.dumps(data), encoding="utf-8")
    images_dir = tmp_path / "val2017"
    images_dir.mkdir()
    for image in data["images"]:
        (images_dir / image["file_name"]).write_bytes(b"jpg")
    return CocoImportConfig(
        annotations=annotations,
        images_dir=images_dir,
        output_dir=tmp_path / "coco_others",
        count=1,
        seed=0,
    )


def make_records(count: int) -> list[ImageRecord]:
    return [
        ImageRecord(image_id=index, file_name=f"{index}.jpg", lines=("1 0.5 0.5 0.1 0.1",))
        for index in range(count)
    ]


def test_yolo_line_normalizes_bbox() -> None:
    line = yolo_line([10, 20, 30, 40], width=100, height=200, class_id=OTHERS_CLASS_ID)
    assert line == "1 0.250000 0.200000 0.300000 0.200000"


def test_yolo_line_clamps_out_of_bounds_bbox() -> None:
    line = yolo_line([90, 90, 30, 30], width=100, height=100, class_id=BALL_CLASS_ID)
    assert line == "0 0.950000 0.950000 0.100000 0.100000"


@pytest.mark.parametrize(
    "bbox",
    (
        [100, 50, 10, 10],  # 이미지 오른쪽 밖
        [10, 10, 0, 5],  # 너비 0
        [10, 10, 5, 0],  # 높이 0
    ),
)
def test_yolo_line_skips_degenerate_bbox(bbox: list[float]) -> None:
    assert yolo_line(bbox, width=100, height=100, class_id=BALL_CLASS_ID) is None


def test_convert_remaps_sports_ball_to_ball_and_rest_to_others() -> None:
    result = convert_instances(make_coco_data(), "sports ball")
    assert len(result.records) == 1
    record = result.records[0]
    assert record.file_name == "000000000010.jpg"
    first_tokens = sorted(line.split()[0] for line in record.lines)
    assert first_tokens == [str(BALL_CLASS_ID), str(OTHERS_CLASS_ID)]


def test_convert_skips_iscrowd_and_unlabeled_images() -> None:
    """crowd 라벨은 세지 않고, 라벨 0줄 이미지는 결과에서 빠진다."""
    result = convert_instances(make_coco_data(), "sports ball")
    assert result.skipped_crowd == 1
    assert result.skipped_unlabeled_images == 2
    assert [record.image_id for record in result.records] == [10]


def test_convert_rejects_missing_ball_category() -> None:
    data = make_coco_data()
    data["categories"] = [{"id": 1, "name": "person"}]
    with pytest.raises(ValueError, match="카테고리"):
        convert_instances(data, "sports ball")


def test_sample_is_deterministic_for_seed() -> None:
    records = make_records(10)
    first = sample_records(records, count=4, seed=7)
    second = sample_records(records, count=4, seed=7)
    assert first == second
    assert [record.image_id for record in first] == sorted(
        record.image_id for record in first
    )


def test_sample_rejects_count_over_pool() -> None:
    with pytest.raises(ValueError, match="샘플링 이미지 수"):
        sample_records(make_records(3), count=4, seed=0)


def test_import_writes_session_layout(tmp_path: Path) -> None:
    config = make_source_tree(tmp_path)
    summary = import_coco(config)
    image = config.output_dir / "images" / "train" / "000000000010.jpg"
    label = config.output_dir / "labels" / "train" / "000000000010.txt"
    assert image.read_bytes() == b"jpg"
    lines = label.read_text(encoding="utf-8").splitlines()
    assert sorted(line.split()[0] for line in lines) == ["0", "1"]
    assert summary.images == 1
    assert summary.ball_instances == 1
    assert summary.others_instances == 1
    assert summary.skipped_crowd == 1
    assert summary.skipped_unlabeled_images == 2


def test_import_uses_injected_copy(tmp_path: Path) -> None:
    config = make_source_tree(tmp_path)
    copied: list[tuple[Path, Path]] = []
    import_coco(config, copy=lambda src, dst: copied.append((src, dst)))
    assert [source.name for source, _ in copied] == ["000000000010.jpg"]


def test_import_rejects_existing_output_without_force(tmp_path: Path) -> None:
    config = make_source_tree(tmp_path)
    stale = config.output_dir / "images" / "train" / "stale.jpg"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    with pytest.raises(ValueError, match="--force"):
        import_coco(config)


def test_import_force_replaces_existing_output(tmp_path: Path) -> None:
    """--force는 이전 세션을 통째로 지워 낡은 파일이 남지 않게 한다."""
    config = make_source_tree(tmp_path)
    stale = config.output_dir / "images" / "train" / "stale.jpg"
    stale.parent.mkdir(parents=True)
    stale.write_bytes(b"old")
    forced = CocoImportConfig(**{**config.__dict__, "force": True})
    summary = import_coco(forced)
    assert summary.images == 1
    assert not stale.exists()
    assert (config.output_dir / "images" / "train" / "000000000010.jpg").is_file()


def test_config_rejects_missing_annotations(tmp_path: Path) -> None:
    config = make_source_tree(tmp_path)
    broken = CocoImportConfig(
        **{**config.__dict__, "annotations": tmp_path / "missing.json"}
    )
    with pytest.raises(ValueError, match="어노테이션"):
        broken.validated()


def test_config_rejects_missing_images_dir(tmp_path: Path) -> None:
    config = make_source_tree(tmp_path)
    broken = CocoImportConfig(**{**config.__dict__, "images_dir": tmp_path / "none"})
    with pytest.raises(ValueError, match="이미지 폴더"):
        broken.validated()


@pytest.mark.parametrize("count", (0, -5))
def test_config_rejects_non_positive_count(tmp_path: Path, count: int) -> None:
    config = make_source_tree(tmp_path)
    broken = CocoImportConfig(**{**config.__dict__, "count": count})
    with pytest.raises(ValueError, match="1 이상"):
        broken.validated()


def test_write_session_rejects_missing_image_file(tmp_path: Path) -> None:
    records = [ImageRecord(image_id=1, file_name="gone.jpg", lines=("0 0.5 0.5 0.1 0.1",))]
    with pytest.raises(ValueError, match="이미지 파일"):
        write_session(records, images_dir=tmp_path, output_dir=tmp_path / "out")
