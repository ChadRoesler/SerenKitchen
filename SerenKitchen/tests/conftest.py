"""The async tests run on asyncio only. anyio's pytest plugin would otherwise try trio too, and a CI runner
with a bare install has no trio to try it on."""
import pytest


@pytest.fixture
def anyio_backend():
    return "asyncio"
