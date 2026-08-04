from pathlib import Path

import pytest

from vision_inspection.training import TrainingConfig, train


class FakeModel:
    def __init__(self) -> None:
        self.options = None

    def train(self, **options):
        self.options = options
        return "trained"


def make_config(tmp_path: Path) -> TrainingConfig:
    data = tmp_path / "data.yaml"
    model = tmp_path / "base.pt"
    data.write_text("names: [mouse]\n", encoding="utf-8")
    model.write_bytes(b"weights")
    return TrainingConfig(
        data=data,
        base_model=model,
        epochs=3,
        image_size=320,
        batch_size=2,
        run_name="test_run",
        output_dir=tmp_path / "runs",
    )


def test_train_passes_validated_options_to_model(tmp_path: Path) -> None:
    fake_model = FakeModel()
    config = make_config(tmp_path)

    result = train(config, model_factory=lambda _path: fake_model)

    assert result == "trained"
    assert fake_model.options == {
        "data": config.data.resolve(),
        "epochs": 3,
        "imgsz": 320,
        "batch": 2,
        "project": config.output_dir.resolve(),
        "name": "test_run",
    }


def test_training_config_rejects_missing_data(tmp_path: Path) -> None:
    config = TrainingConfig(
        data=tmp_path / "missing.yaml",
        base_model=tmp_path / "missing.pt",
    )

    with pytest.raises(ValueError, match="데이터셋 정의 파일"):
        config.validated()


@pytest.mark.parametrize(
    ("field", "value"),
    (("epochs", 0), ("image_size", 0), ("batch_size", 0)),
)
def test_training_config_rejects_invalid_numbers(
    tmp_path: Path, field: str, value: int
) -> None:
    config = make_config(tmp_path)
    options = {**config.__dict__, field: value}

    with pytest.raises(ValueError):
        TrainingConfig(**options).validated()
