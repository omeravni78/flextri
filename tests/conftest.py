import pytest

from flextri.paths import bundled
from flextri.storage import load_template

EXAMPLE = bundled("examples", "placeholder_plan.json")


@pytest.fixture
def template():
    return load_template(EXAMPLE)


@pytest.fixture
def example_path():
    return EXAMPLE


@pytest.fixture(autouse=True)
def _private_data_dir(tmp_path, monkeypatch):
    """Keep every test out of the real per-user data folder."""
    monkeypatch.setenv("FLEXTRI_HOME", str(tmp_path / "flextri-home"))
