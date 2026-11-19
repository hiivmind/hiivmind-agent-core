import shutil

import pytest
from support import FIXTURE, SEQUENCES, Broken, load


@pytest.fixture
def instance():
    return load(FIXTURE)


@pytest.fixture
def sequences():
    return load(SEQUENCES)


@pytest.fixture
def broken(tmp_path):
    root = tmp_path / "instance"
    shutil.copytree(FIXTURE, root, ignore=shutil.ignore_patterns("__pycache__"))
    return Broken(root)


@pytest.fixture
def broken_sequences(tmp_path):
    root = tmp_path / "sequences"
    shutil.copytree(SEQUENCES, root, ignore=shutil.ignore_patterns("__pycache__"))
    return Broken(root)
