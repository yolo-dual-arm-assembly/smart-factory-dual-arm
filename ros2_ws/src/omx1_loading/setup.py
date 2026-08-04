from setuptools import setup

package_name = "omx1_loading"

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
    description="첫 번째 OMX(적재) 노드와 좌표 변환·교시 도구",
    license="MIT",
    entry_points={
        "console_scripts": [
            "loading_node = omx1_loading.loading_node:main",
        ],
    },
)
