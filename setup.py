#!/usr/bin/env python

from setuptools import find_packages, setup

setup(
    name='swaggertosdk',
    version='0.1',
    description='Swagger to SDK tools for Microsoft',
    license='MIT License',
    author='Microsoft Corporation',
    author_email='azpysdkhelp@microsoft.com',
    url='https://github.com/Azure/swagger-to-sdk',
    packages=find_packages(exclude=["tests"]),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'Programming Language :: Python :: 3.7',
        'License :: OSI Approved :: MIT License',
    ],
    install_requires=[
        "azure-devtools[ci_tools]>=1.1.1",
        "requests",
        "cookiecutter",
        "wheel"
    ],
    extras_require={
        'rest': [
            'flask',
            'json-rpc'
        ]
    },
    entry_points = {
        'console_scripts': [
            'generate_sdk=swaggertosdk.generate_sdk:generate_main',
            'generate_package=swaggertosdk.generate_package:generate_main',
        ],
    }
)