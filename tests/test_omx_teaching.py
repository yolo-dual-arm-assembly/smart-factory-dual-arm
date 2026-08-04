from __future__ import annotations

import math

import pytest

from omx1_loading.teaching import OmxTeachingDataset


FRAME_SIZE = (640, 480)


def make_dataset() -> OmxTeachingDataset:
    dataset = OmxTeachingDataset()
    dataset.add_point((100, 100), [0.0, 0.1, 0.2, 0.3, 0.0], FRAME_SIZE)
    dataset.add_point((500, 100), [1.0, 0.2, 0.3, 0.4, 0.0], FRAME_SIZE)
    dataset.add_point((500, 400), [1.0, 0.5, 0.6, 0.7, 0.0], FRAME_SIZE)
    dataset.add_point((100, 400), [0.0, 0.4, 0.5, 0.6, 0.0], FRAME_SIZE)
    return dataset


def test_dataset_requires_area_and_four_points() -> None:
    dataset = OmxTeachingDataset()
    for x in (100, 200, 300, 400):
        dataset.add_point((x, 100), [0.0] * 5, FRAME_SIZE)

    assert not dataset.is_ready


def test_exact_teaching_point_returns_exact_angles() -> None:
    dataset = make_dataset()

    assert dataset.predict((100, 100)) == [0.0, 0.1, 0.2, 0.3, 0.0]
    assert len(dataset.points[0].positions) == 5


def test_center_prediction_stays_between_taught_values() -> None:
    dataset = make_dataset()

    predicted = dataset.predict((300, 250))

    assert predicted == pytest.approx([0.5, 0.3, 0.4, 0.5, 0.0])


def test_prediction_rejects_pixel_outside_taught_area() -> None:
    dataset = make_dataset()

    with pytest.raises(ValueError, match="영역 밖"):
        dataset.predict((50, 50))


def test_nearby_point_replaces_existing_sample() -> None:
    dataset = make_dataset()

    dataset.add_point((102, 101), [0.2, 0.2, 0.2, 0.2, 0.0], FRAME_SIZE)

    assert dataset.point_count == 4
    assert dataset.predict((102, 101))[0] == pytest.approx(0.2)


def test_save_load_roundtrip(tmp_path) -> None:
    dataset = make_dataset()
    path = tmp_path / "teaching.json"

    dataset.save(path)
    restored = OmxTeachingDataset.load(path)

    assert restored.frame_size == FRAME_SIZE
    assert restored.point_count == 4
    assert restored.predict((300, 250)) == pytest.approx(
        dataset.predict((300, 250))
    )


def test_rejects_joint_angle_outside_limits() -> None:
    dataset = OmxTeachingDataset()

    with pytest.raises(ValueError, match="J2"):
        dataset.add_point((100, 100), [0.0, math.pi, 0.0, 0.0, 0.0], FRAME_SIZE)
