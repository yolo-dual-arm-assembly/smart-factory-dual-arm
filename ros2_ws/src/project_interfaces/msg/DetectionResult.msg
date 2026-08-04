# YOLO 탐지 결과 한 프레임. 탐지 실패(detected=false)여도 매 프레임 발행한다.
std_msgs/Header header    # 원본 이미지 프레임의 stamp/frame_id를 그대로 물려받는다
bool detected             # 탐지 성공/실패 flag
string class_name         # 탐지된 클래스 이름 (실패 시 빈 문자열)
float32 confidence        # 탐지 신뢰도 (실패 시 0.0)
float32 cx                # bbox 중심 x (픽셀)
float32 cy                # bbox 중심 y (픽셀)
float32 width             # bbox 너비 (픽셀)
float32 height            # bbox 높이 (픽셀)
