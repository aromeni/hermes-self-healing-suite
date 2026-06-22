from setuptools import setup, find_packages

setup(
    name="hermes",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "click>=8.1.0",
        "gitpython>=3.1.40",
        "pyyaml>=6.0",
        "requests>=2.31.0",
        "PyGithub>=2.1.1",
        "python-dotenv>=1.0.0",
    ],
    entry_points={
        "console_scripts": [
            "hermes=hermes.cli:main",
        ],
    },
    python_requires=">=3.10",
)
