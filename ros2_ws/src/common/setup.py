from setuptools import setup

package_name = "common"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BKD",
    maintainer_email="jinwoong0728@gmail.com",
    description="전 패키지가 공유하는 상수·메시지 규격·장치 접근 코드",
    license="MIT",
    # 노드가 아니라 라이브러리 패키지이므로 실행 파일을 만들지 않는다.
    entry_points={},
)
