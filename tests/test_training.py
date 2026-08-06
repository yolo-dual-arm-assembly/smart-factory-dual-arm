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
    (("epochs", 0), ("image_size", 0), ("batch_size", 0), ("save_period", 0)),
)
def test_training_config_rejects_invalid_numbers(
    tmp_path: Path, field: str, value: int
) -> None:
    config = make_config(tmp_path)
    options = {**config.__dict__, field: value}

    with pytest.raises(ValueError):
        TrainingConfig(**options).validated()


def write_checkpoint(config: TrainingConfig) -> Path:
    """중단된 학습이 남긴 last.pt를 흉내 낸다."""
    checkpoint = config.checkpoint_path()
    checkpoint.parent.mkdir(parents=True, exist_ok=True)
    checkpoint.write_bytes(b"checkpoint")
    return checkpoint


def test_optional_options_are_omitted_by_default(tmp_path: Path) -> None:
    """선택 항목을 안 주면 ultralytics 기본값을 덮어쓰지 않는다."""
    fake_model = FakeModel()
    train(make_config(tmp_path), model_factory=lambda _path: fake_model)

    assert "save_period" not in fake_model.options
    assert "device" not in fake_model.options
    assert "resume" not in fake_model.options


def test_optional_options_are_passed_when_set(tmp_path: Path) -> None:
    fake_model = FakeModel()
    config = TrainingConfig(
        **{**make_config(tmp_path).__dict__, "save_period": 5, "device": "0"}
    )

    train(config, model_factory=lambda _path: fake_model)

    assert fake_model.options["save_period"] == 5
    assert fake_model.options["device"] == "0"


def test_train_resumes_from_checkpoint_when_present(tmp_path: Path) -> None:
    """체크포인트가 있으면 베이스 모델이 아니라 그 파일에서 이어 간다."""
    config = TrainingConfig(**{**make_config(tmp_path).__dict__, "resume": True})
    checkpoint = write_checkpoint(config)
    fake_model = FakeModel()
    loaded: list[Path] = []

    def factory(path: Path) -> FakeModel:
        loaded.append(path)
        return fake_model

    train(config, model_factory=factory)

    assert loaded == [checkpoint]
    assert fake_model.options["resume"] is True


def test_train_starts_fresh_when_checkpoint_missing(tmp_path: Path) -> None:
    """resume을 켜 뒀어도 체크포인트가 없으면 그냥 처음부터 시작한다.

    Colab 학습 셀을 그대로 다시 실행해도 되게 하려는 동작이다.
    """
    config = TrainingConfig(**{**make_config(tmp_path).__dict__, "resume": True})
    fake_model = FakeModel()
    loaded: list[Path] = []

    def factory(path: Path) -> FakeModel:
        loaded.append(path)
        return fake_model

    train(config, model_factory=factory)

    assert loaded == [config.base_model.resolve()]
    assert "resume" not in fake_model.options


def test_validated_allows_missing_base_model_when_resuming(tmp_path: Path) -> None:
    """이어서 학습할 때는 베이스 가중치를 다시 받지 않아도 된다."""
    config = TrainingConfig(
        **{
            **make_config(tmp_path).__dict__,
            "base_model": tmp_path / "gone.pt",
            "resume": True,
        }
    )
    write_checkpoint(config)

    assert config.validated().resume is True

    without_checkpoint = TrainingConfig(
        **{**config.__dict__, "run_name": "other_run"}
    )
    with pytest.raises(ValueError, match="베이스 모델 파일"):
        without_checkpoint.validated()
