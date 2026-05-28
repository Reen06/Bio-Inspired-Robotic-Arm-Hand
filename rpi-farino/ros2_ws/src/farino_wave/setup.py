from setuptools import find_packages, setup

package_name = 'farino_wave'

setup(
    name=package_name,
    version='0.1.0',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages', ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=['setuptools'],
    zip_safe=True,
    maintainer='Reen06',
    maintainer_email='acavelti16@gmail.com',
    description='ROS2 wave demo node for the Farino FR-3 robot arm',
    license='MIT',
    entry_points={
        'console_scripts': [
            'wave_node = farino_wave.wave_node:main',
        ],
    },
)
