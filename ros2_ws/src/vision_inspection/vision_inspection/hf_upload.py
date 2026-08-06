"""학습 산출물(모델·데이터셋)을 Hugging Face Hub에 올리는 도우미.

Colab 학습이 끝나면 ``best.pt``와 데이터셋 압축을 Hub 저장소로 올린다. Drive에만
두면 팀원과 공유하거나 다른 PC에서 내려받기 번거롭기 때문이다.

토큰은 코드나 노트북에 적지 않는다. :func:`resolve_token`이 Colab 보안
비밀(왼쪽 🔑 패널) → ``HF_TOKEN`` 환경 변수 순서로 찾는다.

``huggingface_hub``는 로컬 개발 환경에 없어도 되도록 함수 안에서만 import하고,
테스트는 ``api_factory``로 가짜 API를 주입한다(:mod:`training`의
``model_factory``와 같은 방식).
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

HF_TOKEN_ENV = "HF_TOKEN"

# 커밋 메시지에 어디서 온 업로드인지 남긴다.
COMMIT_PREFIX = "smart-factory-dual-arm"


def resolve_token(token: str | None = None) -> str | None:
    """업로드 토큰을 정한다. 인자 → Colab 보안 비밀 → 환경 변수 순.

    Colab 보안 비밀은 노트북 파일에 토큰이 남지 않는 표준 저장소다. 왼쪽
    🔑 패널에 ``HF_TOKEN`` 이름으로 넣고 "노트북 액세스"를 켜면 잡힌다.
    """
    if token:
        return token
    try:
        from google.colab import userdata  # Colab 런타임에만 있다

        value = userdata.get(HF_TOKEN_ENV)
        if value:
            return value
    except Exception:
        # Colab이 아니거나 보안 비밀이 없다. 환경 변수로 넘어간다.
        pass
    return os.environ.get(HF_TOKEN_ENV) or None


def check_repo_id(repo_id: str) -> str:
    """``아이디/저장소`` 꼴인지 확인한다. 자리표시자를 그대로 두면 바로 알려 준다."""
    repo_id = (repo_id or "").strip()
    if "/" not in repo_id or "<" in repo_id or ">" in repo_id:
        raise ValueError(
            f"Hugging Face 저장소 이름이 올바르지 않습니다: {repo_id!r}\n"
            "'아이디/저장소이름' 꼴로 적어 주세요. 예: gildong/smart-factory-ball"
        )
    return repo_id


def _default_api_factory(token: str) -> Any:
    from huggingface_hub import HfApi

    return HfApi(token=token)


def _require_token(token: str | None) -> str:
    resolved = resolve_token(token)
    if not resolved:
        raise RuntimeError(
            "Hugging Face 토큰을 찾지 못했습니다.\n"
            "1) https://huggingface.co/settings/tokens 에서 Write 권한 토큰을 만들고\n"
            "2) Colab 왼쪽 🔑(보안 비밀)에 이름 HF_TOKEN으로 저장한 뒤 "
            "'노트북 액세스'를 켜세요.\n"
            "   (로컬에서는 환경 변수 HF_TOKEN으로도 됩니다)"
        )
    return resolved


def upload_model(
    repo_id: str,
    files: Sequence[Path],
    *,
    token: str | None = None,
    api_factory: Callable[[str], Any] | None = None,
) -> str:
    """가중치와 부속 파일을 모델 저장소에 올린다.

    ``files`` 중 첫 파일(보통 ``best.pt``)은 반드시 있어야 하고, 나머지는
    있으면 함께 올린다(``results.png``, ``args.yaml`` 같은 기록용).
    같은 이름은 새 커밋으로 덮어써서 저장소가 항상 최신 학습을 가리킨다.
    """
    repo_id = check_repo_id(repo_id)
    files = [Path(f) for f in files]
    if not files:
        raise ValueError("올릴 파일 목록이 비어 있습니다.")
    if not files[0].is_file():
        raise FileNotFoundError(
            f"필수 파일이 없습니다: {files[0]}\n학습이 끝났는지 확인하세요."
        )

    api = (api_factory or _default_api_factory)(_require_token(token))
    api.create_repo(repo_id=repo_id, repo_type="model", exist_ok=True, private=True)

    uploaded: list[str] = []
    for path in files:
        if not path.is_file():
            print(f"[hf] {path.name} 없음 — 건너뜀")
            continue
        api.upload_file(
            path_or_fileobj=str(path),
            path_in_repo=path.name,
            repo_id=repo_id,
            repo_type="model",
            commit_message=f"{COMMIT_PREFIX}: {path.name} 업로드",
        )
        uploaded.append(path.name)

    url = f"https://huggingface.co/{repo_id}"
    print(f"[hf] 모델 업로드 완료 ({', '.join(uploaded)}) → {url}")
    return url


def upload_dataset(
    repo_id: str,
    archive: Path,
    *,
    token: str | None = None,
    force: bool = False,
    api_factory: Callable[[str], Any] | None = None,
) -> str:
    """데이터셋 압축 파일을 데이터셋 저장소에 올린다.

    같은 이름이 이미 올라가 있으면 건너뛴다 — 0.5GB를 학습할 때마다 다시 올리지
    않기 위해서다. 데이터셋을 바꿨다면 ``force=True``로 덮어쓴다.
    """
    repo_id = check_repo_id(repo_id)
    archive = Path(archive)
    if not archive.is_file():
        raise FileNotFoundError(f"데이터셋 압축 파일이 없습니다: {archive}")

    api = (api_factory or _default_api_factory)(_require_token(token))
    api.create_repo(repo_id=repo_id, repo_type="dataset", exist_ok=True, private=True)

    url = f"https://huggingface.co/datasets/{repo_id}"
    if not force and api.file_exists(
        repo_id=repo_id, filename=archive.name, repo_type="dataset"
    ):
        print(f"[hf] {archive.name}이(가) 이미 있어 건너뜁니다 (다시 올리려면 force=True)")
        return url

    api.upload_file(
        path_or_fileobj=str(archive),
        path_in_repo=archive.name,
        repo_id=repo_id,
        repo_type="dataset",
        commit_message=f"{COMMIT_PREFIX}: {archive.name} 업로드",
    )
    print(f"[hf] 데이터셋 업로드 완료 ({archive.name}) → {url}")
    return url


def model_upload_files(run_dir: Path) -> list[Path]:
    """학습 결과 폴더에서 올릴 파일 목록을 만든다.

    첫 항목(``best.pt``)이 필수이고 나머지는 있으면 올린다. 무거운
    ``epoch*.pt`` 스냅샷은 일부러 뺀다 — 되돌리기용은 Drive에 이미 있다.
    """
    run_dir = Path(run_dir)
    return [
        run_dir / "weights" / "best.pt",
        run_dir / "results.png",
        run_dir / "args.yaml",
    ]
