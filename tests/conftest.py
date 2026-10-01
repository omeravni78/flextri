from pathlib import Path

import pytest

from flextri.storage import load_template

EXAMPLE = Path(__file__).parent.parent / "examples" / "placeholder_plan.json"


@pytest.fixture
def template():
    return load_template(EXAMPLE)


@pytest.fixture
def example_path():
    return EXAMPLE
