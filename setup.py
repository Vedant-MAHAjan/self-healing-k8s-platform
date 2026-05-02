from setuptools import setup, find_packages

with open("README.md", "r", encoding="utf-8") as fh:
    long_description = fh.read()

with open("requirements.txt", "r", encoding="utf-8") as fh:
    requirements = [line.strip() for line in fh if line.strip() and not line.startswith("#")]

setup(
    name="self-healing-k8s-operator",
    version="0.1.0",
    author="Your Name",
    author_email="your.email@example.com",
    description="AI-powered self-healing Kubernetes operator",
    long_description=long_description,
    long_description_content_type="text/markdown",
    url="https://github.com/yourusername/self-healing-k8s",
    packages=find_packages(),
    classifiers=[
        "Development Status :: 4 - Beta",
        "Intended Audience :: Developers",
        "Topic :: System :: Clustering",
        "License :: OSI Approved :: MIT License",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.11",
    ],
    python_requires=">=3.11",
    install_requires=requirements,
    include_package_data=True,
    package_data={"k8s_operator": ["config_manager/*.yaml"]},
    entry_points={
        "console_scripts": [
            "self-healing-operator=k8s_operator.main:main",
        ],
    },
)
