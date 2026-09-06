"""Source package metadata; the desktop installer is built with pyappify."""

import re
from pathlib import Path

import setuptools


ROOT = Path(__file__).resolve().parent
version = re.search(r'^version = "([0-9]+\.[0-9]{2}\.[0-9]{2})"',
                    (ROOT / 'config.py').read_text(encoding='utf-8'), re.M).group(1)
requirements = [line.strip() for line in (ROOT / 'requirements.txt').read_text(encoding='utf-8').splitlines()
                if line.strip() and not line.lstrip().startswith('#')]

setuptools.setup(
    name='ok-ww',
    version=version,  # Python package metadata normalizes zero-padded components.
    author='ok-oldking',
    author_email='firedcto@gmail.com',
    description='Automation with Computer Vision for Python',
    url='https://github.com/xihuojun2020-tech/okww-custom',
    packages=setuptools.find_packages(include=['src', 'src.*']),
    include_package_data=True,
    classifiers=[
        'Programming Language :: Python :: 3.12',
        'Intended Audience :: Developers',
        'License :: OSI Approved :: MIT License',
        'Operating System :: Microsoft :: Windows',
    ],
    install_requires=requirements,
    python_requires='>=3.12',
)
