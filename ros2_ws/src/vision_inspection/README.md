# vision_inspection — YOLO 검사 (담당: 1·2번)

바구니 안 공 개수와 불량을 판정해
[`InspectionResult`](../../../common/messages.py)로 돌려주는 것이 이 패키지의
최종 책임입니다. 1번이 모델 학습·데이터셋(`train.py`, `training.py`,
`models.py`), 2번이 카메라·검사(`vision_node.py`, `inspection_logic.py`)를 맡습니다.

| 파일 | 역할 |
|---|---|
| `inspection_logic.py` | 바구니 검사 → `InspectionResult` (coordinator가 쓰는 진입점) |
| `vision_node.py` | ROS2 노드: 이미지 토픽 구독 → 추론 → `/yolo/detection` 발행 |
| `analysis.py` | 이미지 폴더 일괄 추론 루프 (GUI가 사용) |
| `models.py` | 사용 가능한 모델 목록과 다운로드 |
| `training.py` | 학습 설정 검증과 실행 |
| `train.py` | 학습 CLI |
| `detect.py` | 웹캠 실시간 탐지 CLI |
| `config/data.yaml` | 데이터셋 정의 (이미지·라벨은 루트 `train_set/`) |

## 실행

```powershell
python -m vision_inspection.train --epochs 100 --batch 16
python -m vision_inspection.detect --model yolov8n.pt
python -m vision_inspection.inspection_logic --source object/test.jpg
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

- `BALL_CLASS_NAMES`, `DEFECT_CLASS_NAMES`를 실제 학습 데이터셋 클래스 이름으로
  교체합니다.
- 학습된 `best.pt`는 Git에 올리지 않습니다. Release나 공유 드라이브로 전달하고
  레포 루트의 `models/`에 두면 GUI 모델 목록에 나타납니다.
