from setuptools import setup

package_name = "vision_inspection"

setup(
    name=package_name,
    version="0.1.0",
    packages=[package_name],
    data_files=[
        ("share/ament_index/resource_index/packages", ["resource/" + package_name]),
        ("share/" + package_name, ["package.xml"]),
        ("share/" + package_name + "/launch", ["launch/detection.launch.py"]),
        (
            "share/" + package_name + "/config",
            ["config/data.yaml", "config/class_scheme.yaml"],
        ),
    ],
    install_requires=["setuptools"],
    zip_safe=True,
    maintainer="BKD",
    maintainer_email="jinwoong0728@gmail.com",
    description="YOLO 검사 노드와 학습·추론 도구",
    license="MIT",
    entry_points={
        "console_scripts": [
            "vision_node = vision_inspection.vision_node:main",
        ],
    },
)
