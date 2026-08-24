# vision_inspection — YOLO 검사 (담당: 1·2번)

바구니 안 공 개수와 불량을 판정해
[`InspectionResult`](../common/common/messages.py)로 돌려주는 것이 이 패키지의
최종 책임입니다. 1번이 모델 학습·데이터셋(`train.py`, `training.py`,
`models.py`), 2번이 카메라·검사(`vision_node.py`, `inspection_logic.py`)를 맡습니다.

| 파일 | 역할 |
|---|---|
| `inspection_logic.py` | 바구니 검사 → `InspectionResult` (coordinator가 쓰는 진입점) |
| `class_scheme.py` | 검사 클래스 스킴 로드·검증 (`config/class_scheme.yaml`) |
| `stability.py` | 판정 안정화 게이트 — 개수가 흔들리는 동안 확정을 미룸 |
| `vision_node.py` | ROS2 노드: 이미지 토픽 구독 → 추론 → `/yolo/detection` 발행 |
| `analysis.py` | 이미지 폴더 일괄 추론 루프 (GUI가 사용) |
| `models.py` | 사용 가능한 모델 목록과 다운로드 |
| `training.py` | 학습 설정 검증과 실행 |
| `train.py` | 학습 CLI |
| `detect.py` | 웹캠 실시간 탐지 CLI |
| `coco_import.py` | COCO 샘플을 ball/others 학습 세션으로 변환하는 CLI |
| `colab.py` / `hf_upload.py` | Colab Drive 도우미 / 학습 결과 Hugging Face 업로드 |
| `notebooks/train_colab.ipynb` | Colab GPU 학습 노트북 (데이터 준비→학습→업로드) |
| `config/` | `data.yaml`(데이터셋 정의), `class_scheme.yaml`(검사 기준) |

## 실행

```powershell
python -m vision_inspection.train --epochs 100 --batch 16
python -m vision_inspection.detect --model yolov8n.pt
python -m vision_inspection.inspection_logic --source object/test.jpg
python -m vision_inspection.coco_import               # train_set/coco_others 생성(기본 800장)
```

`coco_import`는 COCO val2017을 미리 받아 둬야 합니다(1회, 약 1GB):

```bash
mkdir -p train_set/coco_src && cd train_set/coco_src
wget http://images.cocodataset.org/zips/val2017.zip && unzip val2017.zip
wget http://images.cocodataset.org/annotations/annotations_trainval2017.zip \
    && unzip annotations_trainval2017.zip
```

## 규격 (바꾸려면 통합 담당자와 합의)

```python
InspectionResult.from_counts(total_count=3, defect_count=0)
# → {"total_count": 3, "defect_count": 0, "result": "PASS"}
```

`result`는 문자열을 직접 적지 말고 `common.constants.RobotState`를 씁니다.
판정 기준(`defect_count == 0`이면 PASS)은 `InspectionResult.from_counts()`
한 곳에만 둡니다.

## 남은 일

- 운영 신뢰도 임계값을 학습된 모델에 맞게 올립니다. `common/constants.py`의
  `CONFIDENCE_THRESHOLD = 0.1`은 사전학습 COCO 모델용으로 낮춘 값이라, 직접
  학습한 `best.pt`에서는 저신뢰 오탐이 REJECT 오판정으로 이어질 수 있습니다.
  적정값은 val 결과의 `F1_curve.png`로 확인합니다.
- 학습된 `best.pt`는 Git에 올리지 않습니다. Colab 노트북 9번 셀(Hugging Face
  업로드)로 전달하고, 레포 루트의 `models/`에 두면 GUI 모델 목록에 나타납니다.
