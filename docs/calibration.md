# 좌표 보정

카메라가 본 화면 픽셀을 로봇이 움직일 좌표(미터)로 바꾸는 단계입니다. 담당은
3번이며 코드는 [`omx1_loading`](../ros2_ws/src/omx1_loading) 패키지에 있습니다.

| 파일 | 역할 |
|---|---|
| `coordinate_transform.py` | 픽셀 ↔ 로봇 좌표 Homography 변환 (`OmxCalibration`) |
| `camera_calibration.py` | 화면을 클릭해 대응점을 모으는 Tkinter 창 |
| `config/calibration.json` | 계산된 변환 행렬 (장비별 값이라 Git에 올리지 않음) |

## 전제

eye-to-hand 구성입니다. 카메라는 고정된 위치에서 테이블을 내려다보고, Z축은
테이블 높이로 고정합니다. **카메라 위치나 해상도가 바뀌면 보정을 다시 해야
합니다.**

## 보정 절차

1. 메인 GUI 사이드바 `카메라 선택`에서 사용할 카메라를 고릅니다.
2. `OMX 비전 제어 → 1. 좌표 캘리브레이션`을 실행합니다.
3. 화면에서 기준점을 클릭하고, 그 지점의 실제 로봇 좌표(미터)를 입력합니다.
4. 최소 4점을 서로 다른 위치에 찍습니다. 한 직선 위에 몰리면 변환이 계산되지
   않습니다. 화면 네 모서리 쪽에 넓게 잡을수록 정확합니다.
5. 저장하면 `ros2_ws/src/omx1_loading/config/calibration.json`이 만들어집니다.

## 코드에서 쓰기

```python
from omx1_loading.coordinate_transform import OmxCalibration
from common.constants import OMX_CALIBRATION_PATH
from common.messages import RobotPosition

calibration = OmxCalibration.load(OMX_CALIBRATION_PATH)
x, y, z = calibration.pixel_to_robot(center_x, center_y)
position = RobotPosition(x, y, z)
```

보정 파일이 아직 없을 때는 `make_full_frame_calibration(width, height)`로 화면
전체를 보수적인 작업 사각형에 대응시켜 임시로 쓸 수 있습니다. 실제 이동
정확도는 보장되지 않으므로 시험용으로만 씁니다.

## 확인 방법

```powershell
python -m pytest tests/test_omx_kinematics.py -q
```

정기적으로 같은 물체를 같은 자리에 두고 `pixel_to_robot` 결과가 이전과 비슷한지
비교하면 카메라가 밀렸는지 알 수 있습니다.
