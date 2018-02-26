#!/usr/bin/env python

from setuptools import find_packages, setup

setup(
    name='swaggertosdk',
    version='0.1',
    description='Swagger to SDK tools for Microsoft',
    license='MIT License',
    author='Microsoft Corporation',
    author_email='azpysdkhelp@microsoft.com',
    url='https://github.com/lmazuel/swagger-to-sdk',
    packages=find_packages(exclude=["tests"]),
    classifiers=[
        'Development Status :: 4 - Beta',
        'Programming Language :: Python',
        'Programming Language :: Python :: 3',
        'Programming Language :: Python :: 3.6',
        'License :: OSI Approved :: MIT License',
    ],
    install_requires=[
        "PyGithub>=1.36", # Can Merge PR after 1.36
        "GitPython",
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