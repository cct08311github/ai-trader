from setuptools import setup, find_packages

setup(
    name="openclaw-ai-trader",
    version="1.0.0",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    install_requires=[
        "shioaji>=1.0",
    ],
    python_requires=">=3.10",
)
