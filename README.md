# Smart Factory Dual Arm

YOLO 검사, USB 카메라, ROBOTIS OMX 로봇팔 제어를 하나의 Tkinter 운영 GUI와
ROS2 워크스페이스로 묶은 프로젝트입니다. 기본 사용 환경은 **Linux**이며,
Windows에서는 ROS2 없이 GUI·CLI·테스트를 실행할 수 있습니다.

분석할 이미지는 `object/`, 결과는 모델별 `result/`, YOLO 가중치는 `models/`에
저장됩니다. 모델·데이터셋·분석 결과·장비별 보정값은 Git에 포함하지 않습니다.

## 현재 구현 상태

| 구성 | 현재 상태 |
| --- | --- |
| 통합 GUI | 이미지/일괄 분석, 웹캠 탐지, 카메라 선택, OMX 수동 제어·교시 UI 구현 |
| `vision_inspection` | ROS2 `vision_node`, 학습·웹캠 CLI, 검사 로직 구현 |
| `omx1_loading` | ROS2 `loading_node`, 좌표 변환·교시·비전 실행기 구현. 노드의 실제 팔 명령은 아직 자리표시자 |
| `omx2_sorting` | 이동·정상·불량 모션 스캐폴드만 있으며 ROS2 노드는 미작성 |
| `system_coordinator` | 상태 머신과 장비 없는 공정 흐름 로직만 있으며 ROS2 노드는 미작성 |
| `system_monitor` | 통합 GUI만 있으며 ROS2 노드는 미작성 |
| ROS2 인터페이스 | `DetectionResult.msg`, `InspectBasket.srv`, `LoadBalls.action`, `SortBasket.action` 정의 완료. 이를 제공하는 **서버 노드는 아직 미작성** |

완료되지 않은 노드까지 실제 공정에 연결된 것으로 가정하면 안 됩니다. 상세 구조와
통신 규격은 [시스템 구조](docs/system_architecture.md)와
[통신 프로토콜](docs/communication_protocol.md)을 참고하십시오.

## Linux 권장 환경

- 신규 설치 권장: **Ubuntu 24.04 64비트**
- Python: **3.11 이상**
- 프로젝트 개발 기준: **Python 3.11.9**
- Ubuntu 24.04 기본 Python 3.12도 지원 범위에 포함
- ROS2: Ubuntu 24.04/Jazzy 또는 Ubuntu 22.04/Humble
- 최초 패키지 및 YOLO 모델 설치를 위한 인터넷 연결
- 카메라 사용 시 USB 웹캠 또는 V4L2 호환 카메라
- 로봇 사용 시 OMX 전원, USB 연결, Linux 시리얼 포트 권한

Ubuntu 22.04의 기본 Python 3.10은 통합 GUI의 최소 버전보다 낮습니다. 22.04에서
GUI를 실행할 때는 Python 3.11 이상을 별도로 준비하고, 그 인터프리터로 `.venv`를
만드십시오. ROS2 빌드와 실행 환경은 배포판 Python 및 ROS2 버전 호환성도 함께
확인해야 합니다.

## Linux 첫 설치

### 1. 저장소 준비

GitHub에서 저장소를 클론한 뒤 저장소 루트로 이동합니다.

```bash
git clone https://github.com/yolo-dual-arm-assembly/smart-factory-dual-arm.git
cd smart-factory-dual-arm
```

이미 클론했다면 `main.py`와 `requirements.txt`가 있는 폴더에서 시작하면 됩니다.

```bash
pwd
ls main.py requirements.txt
```

### 2. 시스템 패키지 설치

Ubuntu/Debian에서는 Tkinter와 가상환경 도구를 시스템 패키지로 설치합니다.
Tkinter는 `pip` 패키지가 아닙니다.

```bash
sudo apt update
sudo apt install -y python3-venv python3-tk
python3 --version
```

Fedora에서는 Tkinter를 다음과 같이 설치합니다.

```bash
sudo dnf install -y python3-tkinter
```

### 3. 프로젝트 가상환경과 Python 패키지 설치

시스템 Python에 `pip install`하지 말고 저장소별 `.venv`를 사용합니다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

`requirements.txt`는 Pillow, Ultralytics, Dynamixel SDK를 설치하며 Ultralytics의
의존성으로 PyTorch와 OpenCV도 설치됩니다. 설치 용량이 크므로 충분한 디스크
공간을 준비하십시오.

설치된 인터프리터와 주요 모듈을 확인합니다.

```bash
python -c "import sys; print(sys.version); print(sys.executable)"
python -c "import cv2; from PIL import Image; from ultralytics import YOLO; print('의존성 확인 완료')"
python -m tkinter
```

마지막 명령에서 작은 Tk 창이 나타나면 GUI 실행 준비가 끝난 것입니다.

### 4. OMX 시리얼 포트 권한 설정

OMX를 사용하는 Linux 계정은 보통 `dialout` 그룹에 속해야 합니다. 다음 작업은
컴퓨터마다 한 번만 하면 되며, 재부팅 이후에도 유지됩니다.

```bash
sudo usermod -aG dialout "$USER"
sudo reboot
```

재부팅 후 다음 명령의 출력에 `dialout`이 포함되는지 확인합니다.

```bash
groups
```

`sudo chmod 666 /dev/ttyACM0`은 장치를 다시 연결하거나 재부팅하면 사라지는 임시
설정이므로 사용하지 않습니다. 앱은 Linux 시리얼 장치가 존재하지만 권한이 없으면
연결 오류창에 현재 사용자에 맞춘 다음 명령을 표시합니다.

```text
sudo usermod -aG dialout <사용자>
sudo reboot
```

포트는 `/dev/ttyACM*`, `/dev/ttyUSB*`, U2D2, FTDI, CP210, CH340 등의 USB 시리얼
정보를 보고 자동 선택합니다. USB 장치가 여러 개면 `/dev/ttyACM0` 번호가 바뀔 수
있으므로 다음 목록의 `/dev/serial/by-id/...` 경로를 GUI 포트 입력칸이나 `--port`
옵션에 직접 지정하는 방법이 더 안정적입니다.

```bash
ls -l /dev/serial/by-id/
```

### 5. 실행

가상환경을 활성화한 터미널에서 실행합니다.

```bash
python main.py
```

활성화하지 않았다면 가상환경 Python을 직접 지정할 수 있습니다.

```bash
./.venv/bin/python main.py
```

`main.py`는 실행 중인 Python 버전과 `tkinter`, Pillow, OpenCV, Ultralytics를 먼저
검사합니다. 준비된 `.venv`가 있으면 해당 Python으로 자동 전환하고, 아무 환경도
준비되지 않은 첫 실행이면 Linux용 설치 명령과 VS Code 인터프리터 선택 방법을
출력한 뒤 종료합니다.

## VS Code에서 실행

1. VS Code로 저장소 루트를 엽니다.
2. `Ctrl+Shift+P`를 누릅니다.
3. `Python: Select Interpreter`를 선택합니다.
4. 저장소의 `.venv/bin/python`을 선택합니다.
5. `main.py`를 열고 실행 버튼을 누릅니다.

시스템 `/usr/bin/python3`가 선택된 상태에서 처음 실행해도 `main.py`가 Linux용
설치 절차를 안내합니다. `.venv` 설치가 끝나면 반드시 인터프리터를 다시 선택하거나
VS Code를 다시 열어 주십시오. `.vscode/`는 OS별 절대 경로가 저장되는 일을 막기
위해 Git에서 제외합니다.

## 통합 GUI 사용

### 이미지 분석

분석할 이미지를 `object/`에 넣습니다. 지원 확장자는 `.png`, `.jpg`, `.jpeg`,
`.bmp`입니다. 분석 결과는 다음과 같이 모델별 폴더에 저장됩니다.

```text
result/
├── best/
├── yolov8n/
├── yolov8m/
└── yolo11m-seg/
```

기존 결과가 있으면 재사용하거나 다시 분석할 수 있습니다. 생성된 `result/` 파일에
의존하지 말고, 필요한 원본 이미지는 실행 전에 `object/`에 준비하십시오.

### YOLO 모델

처음 실행할 때 다음 공식 모델이 없으면 `models/`에 자동 다운로드합니다.

- `yolov8n.pt`: 가장 가볍고 빠른 객체 탐지 모델
- `yolov8m.pt`: 속도와 정확도의 균형을 고려한 객체 탐지 모델
- `yolo11m-seg.pt`: 객체 윤곽 마스크를 만드는 세그멘테이션 모델이며 GUI 기본값

`best.pt`는 로컬 커스텀 모델이므로 자동 다운로드하지 않습니다. 파일이 있을 때만
GUI의 `Robot Custom` 항목에 표시됩니다. 학습 데이터는 `train_set/`, 데이터셋
정의는 `ros2_ws/src/vision_inspection/config/data.yaml`에 둡니다.

```bash
python -m vision_inspection.train
python -m vision_inspection.train --epochs 100 --batch 16
```

학습 결과 `runs/custom_detect/weights/best.pt`를 `models/best.pt`로 복사하면 GUI에서
선택할 수 있습니다. 가중치와 학습 결과는 Git에서 제외됩니다.

### 카메라 선택

사이드바의 `카메라 선택`에서 웹캠 실시간 탐지와 OMX 비전 제어에 사용할 장치를
고릅니다.

- 시작할 때 연결된 카메라를 조회하고 한 대뿐이면 자동 선택합니다.
- 실행 중 연결 상태가 바뀌면 `다시 검색`을 누릅니다.
- 검색은 카메라를 실제로 열기 때문에 웹캠 창이나 OMX 작업 중에는 실행할 수
  없습니다.
- 장치를 찾지 못하면 0~3번 인덱스를 직접 선택할 수 있습니다.

Linux에서는 필요할 때 다음 명령으로 V4L2 장치를 확인할 수 있습니다.

```bash
ls -l /dev/video*
```

### OMX 수동 제어와 Mouse 교시

메인 GUI의 `OMX 비전 제어`에서 포트를 확인한 뒤 수동 제어 또는 `Mouse 관절 교시
모드`를 실행합니다. 교시 모드에서는 다음 순서로 자세를 저장합니다.

1. `로봇 연결`
2. 화면에서 Mouse 탐지 후 `Mouse 위치 고정`
3. 슬라이더로 실제 그리퍼 자세 조정
4. `고정 위치 + 실제 관절값 저장`

좌상·상·우상, 좌·중앙·우, 좌하·하·우하의 9개 교시점을 권장합니다. 최소 4개
교시점이 서로 둘러싸는 영역을 만들면 `교시값으로 Mouse 이동`을 사용할 수 있고,
자동 이동은 교시 영역 안에서만 허용됩니다. 카메라 위치나 해상도를 바꾸면 다시
교시해야 합니다.

장비별 파일은 다음 위치에 저장되며 Git에 포함되지 않습니다.

- `ros2_ws/src/omx1_loading/config/omx_mouse_teaching.json`
- `ros2_ws/src/omx1_loading/config/calibration.json`

## 프로젝트 구조

```text
smart-factory-dual-arm/
├── main.py                  # 통합 GUI 진입점과 런타임 검사
├── ros2_ws/
│   └── src/
│       ├── common/          # 경로, 메시지, 카메라, 시리얼, OMX, bootstrap
│       ├── project_interfaces/
│       ├── vision_inspection/
│       ├── omx1_loading/
│       ├── omx2_sorting/
│       ├── system_coordinator/
│       └── system_monitor/
├── docs/                    # 구조, 통신, 캘리브레이션 문서
├── models/                  # 모델 가중치, Git 제외
├── train_set/               # 학습 데이터, Git 제외
├── object/                  # 분석 입력 이미지
├── result/                  # 분석 결과, Git 제외
├── tests/
├── requirements.txt
└── pyproject.toml
```

ROS2 패키지는 `pkg/pkg/*.py` 구조입니다. 공용 코드인 `common`도 같은 구조의
워크스페이스 패키지라 `ros2_ws/src/common/common/`에 있고, import 경로는
`from common.messages import ...` 그대로입니다. `main.py`는
`common.bootstrap.ensure_workspace_path()`로 import 경로를 등록하므로 설치 없이도
GUI가 실행됩니다. 다른 폴더에서도 모듈 명령과 `yolo-app`을 사용하려면 개발 모드로
설치합니다.

```bash
python -m pip install -e .
```

| 목적 | 명령 |
| --- | --- |
| 통합 GUI | `python main.py` |
| 설치 후 통합 GUI | `yolo-app` |
| YOLO 학습 | `python -m vision_inspection.train` |
| 웹캠 CLI 탐지 | `python -m vision_inspection.detect` |
| 장비 없는 공정 흐름 | `python -m system_coordinator.main_controller` |
| OMX 연결·비전 CLI | `python -m omx1_loading.run_vision_pick --help` |
| OMX 수동 제어 GUI | `python -m system_monitor.ui.omx_manual_control` |

## ROS2 빌드와 실행

ROS2는 Linux에서만 빌드합니다. 현재 colcon 빌드 대상은 `common`,
`project_interfaces`, `vision_inspection`, `omx1_loading`이며 나머지 패키지는 아직
ROS2 노드가 없습니다.

배포판별 의존성 설치, `colcon build`, 카메라 드라이버와 노드 실행 절차는
[ROS2 워크스페이스 README](ros2_ws/README.md)를 따르십시오.

## Windows 보조 실행

Windows에서는 ROS2 빌드 없이 통합 GUI, CLI와 테스트를 실행할 수 있습니다.
python.org의 64비트 Python 3.11 이상을 설치할 때 `Add python.exe to PATH`, Python
Launcher, `tcl/tk and IDLE`을 포함하십시오. MSYS2/MinGW Python은 PyTorch와
OpenCV 휠 호환성 때문에 사용할 수 없습니다.

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -r .\requirements.txt
python .\main.py
```

VS Code에서는 `.venv\Scripts\python.exe`를 인터프리터로 선택합니다. Linux에서
만든 `.venv`와 Windows에서 만든 `.venv`는 서로 복사해 사용할 수 없습니다.

## 문제 해결

### 실행하면 의존성 설치 안내만 나옴

현재 선택된 Python에 필수 모듈이 없고 준비된 `.venv`도 없는 상태입니다. 위의
Linux 첫 설치 절차를 완료한 다음 VS Code에서 `.venv/bin/python`을 선택합니다.
시스템 Python에 직접 `pip install`하지 마십시오.

### `No module named '_tkinter'`

```bash
sudo apt install -y python3-tk       # Ubuntu/Debian
sudo dnf install -y python3-tkinter  # Fedora
```

Tkinter를 설치한 Python과 `.venv`를 만든 Python이 같아야 합니다.

### OMX 포트 권한 오류

```bash
sudo usermod -aG dialout "$USER"
sudo reboot
```

앱의 오류창에도 같은 명령이 표시됩니다. 재부팅 후 `groups`와 장치 소유권을
확인합니다.

```bash
groups
ls -l /dev/ttyACM* /dev/ttyUSB*
```

장치 파일 자체가 없다면 권한 문제가 아니라 USB 케이블, 전원 또는 포트 문제일 수
있습니다.

### 설치했는데 모듈을 찾지 못함

```bash
which python
python -c "import sys; print(sys.executable)"
python -m pip --version
```

세 경로가 모두 저장소의 `.venv`를 가리켜야 합니다. VS Code에서도 같은
인터프리터를 선택하십시오.

### 모델 다운로드 실패

인터넷 연결과 디스크 여유 공간을 확인합니다. 자동 다운로드를 다시 시도하거나
가상환경에서 직접 준비할 수 있습니다.

```bash
python -c "from ultralytics import YOLO; YOLO('yolov8n.pt')"
python -c "from ultralytics import YOLO; YOLO('yolov8m.pt')"
python -c "from ultralytics import YOLO; YOLO('yolo11m-seg.pt')"
```

직접 내려받은 파일은 프로젝트의 `models/`에 두십시오.

## 개발 확인

개발 의존성까지 설치하려면 다음 명령을 사용합니다.

```bash
python -m pip install -e ".[dev]"
```

변경 제출 전 저장소 루트에서 컴파일 검사와 테스트를 실행합니다.

```bash
python -m compileall common main.py ros2_ws/src
python -m pytest -q
```

GUI 또는 추론 변경은 모델 선택, 단일/일괄 이미지 분석, 캐시된 결과 표시, 웹캠과
OMX 창 종료까지 수동으로 확인하십시오.
