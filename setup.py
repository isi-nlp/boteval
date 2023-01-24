import sys
import re
from setuptools import setup, find_namespace_packages
from pathlib import Path


with open("requirements.txt") as f:
    lines = f.readlines()
    reqs = []
    for line in lines:
        line = line.strip()
        if ' #' in line: # line with comment text as suffix
            line = line.split(' #')[0].strip()
        if not line or line.startswith("#"):
            continue  # skip empty and comment lines
        reqs.append(line)


PACKAGE = 'boteval'
init_file = Path(__file__).parent / PACKAGE / '__init__.py'
init_txt = init_file.read_text()


version = re.search(
    r'''__version__ = ['"]([0-9.]+(-dev)?)['"]''', init_txt).group(1)
description = 'Chat Bot Evaluation'

assert version
assert description

packages = find_namespace_packages(include=[f"{PACKAGE}*"])
print(f"packages:: {packages}", file=sys.stderr)

setup(name=PACKAGE,
      version=version,
      description=description,
      author="Thamme Gowda",
      author_email="tgowdan@gmail.com",
      long_description=Path("README.md").read_text(),
      long_description_content_type="text/markdown",
      url="https://github.com/thammegowda/boteval",
      python_requires=">=3.9",
      packages=packages,
      license="Apache",
      install_requires=reqs,
      include_package_data=True,
      zip_safe=False,
      entry_points={
          "console_scripts": [
              "boteval=boteval.app:main",
              "boteval-quickstart=boteval.quickstart:main",
              ]
          },
      classifiers=[
          "Programming Language :: Python :: 3",
          "Programming Language :: Python :: 3.9",
          "Programming Language :: Python :: 3.10",
          "License :: OSI Approved :: MIT License",
          "Topic :: Scientific/Engineering :: Artificial Intelligence",
      ],
    )
