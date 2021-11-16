import asyncio
import json
import logging
import os
import subprocess
import time
from asyncio import coroutine
from os.path import isfile
from statistics import mean
from typing import Dict, List, Tuple

import pytest
from aiohttp.web_response import Response

from vm_supervisor.conf import settings
from vm_supervisor.models import VmHash
from vm_supervisor.pubsub import PubSub
from vm_supervisor.run import run_code_on_request, pool, run_code_on_event
from vm_supervisor.storage import get_runtime_path

logger = logging.getLogger(__name__)


class FakeRequest:
    headers: Dict[str, str]
    raw_headers: List[Tuple[bytes, bytes]]


@pytest.fixture
def fake_request():
    ref = VmHash("cad11970efe9b7478300fd04d7cc91c646ca0a792b9cc718650f86e1ccfac73e")

    fake_request = FakeRequest()
    fake_request.match_info = {"ref": ref, "suffix": "/"}
    fake_request.method = "GET"
    fake_request.query_string = ""

    fake_request.headers = {"host": "127.0.0.1", "content-type": "application/json"}
    fake_request.raw_headers = [
        (name.encode(), value.encode()) for name, value in fake_request.headers.items()
    ]

    async def fake_read() -> bytes:
        return b""
    fake_request.read = fake_read

    return fake_request


@pytest.fixture
async def runtime():
    assert settings.FAKE_DATA
    ref = VmHash("cad11970efe9b7478300fd04d7cc91c646ca0a792b9cc718650f86e1ccfac73e")

    runtime_path = await get_runtime_path(ref)
    if not isfile(runtime_path):
        raise FileNotFoundError("Runtime not found, run `create_disk_image.sh` first.")


@pytest.fixture
async def vm_pool():
    yield pool
    await pool.stop()


@pytest.fixture
def test_settings():
    settings.FAKE_DATA = True
    settings.PRINT_SYSTEM_LOGS = True

    # Does not make sense in tests
    settings.WATCH_FOR_UPDATES = False

    settings.NETWORK_INTERFACE = "tap0"  # Docker

    # First test all methods
    settings.REUSE_TIMEOUT = 0.1

    settings.setup()


@pytest.fixture(scope="module")
def redis_server():
    process = subprocess.Popen("redis-server")
    yield process
    process.terminate()


@pytest.mark.asyncio
async def test_get_index(fake_request: FakeRequest, runtime, vm_pool, test_settings):
    path = "/"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200


@pytest.mark.asyncio
async def test_get_environ(fake_request: FakeRequest, runtime, vm_pool, test_settings):
    path = "/environ"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200


@pytest.mark.asyncio
async def test_get_messages(fake_request: FakeRequest, runtime, vm_pool, test_settings):
    path = "/messages"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200


@pytest.mark.asyncio
async def test_set_cache_key(fake_request: FakeRequest, runtime, vm_pool, test_settings, redis_server):
    path = "/cache/set/foo/bar"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200

    path = "/cache/get/foo"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200
    assert json.loads(response.text) == "bar"


@pytest.mark.asyncio
async def test_list_cache_keys(fake_request: FakeRequest, runtime, vm_pool, test_settings, redis_server):
    path = "/cache/set/foo/bar"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200

    path = "/cache/keys"

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200
    assert json.loads(response.text) == ["foo"]


@pytest.mark.asyncio
async def test_get_internet(fake_request: FakeRequest, runtime, vm_pool, test_settings):
    path = "/internet"

    logging.basicConfig(
        level=logging.DEBUG,
        format="%(relativeCreated)4f | %(levelname)s | %(message)s",
    )

    print(settings.json())

    fake_request.match_info["suffix"] = path
    response: Response = await run_code_on_request(
        vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
    )
    assert response.status == 200
    print(response.text)

@pytest.mark.asyncio
async def test_benchmark(fake_request: FakeRequest, runtime, vm_pool, test_settings):
    runs = 10
    bench: List[float] = []

    # Disable VM timeout to exit benchmark properly
    settings.REUSE_TIMEOUT = 0 if runs == 1 else 0.1
    path = "/"
    for run in range(runs):
        t0 = time.time()
        fake_request.match_info["suffix"] = path
        response: Response = await run_code_on_request(
            vm_hash=fake_request.match_info['ref'], path=path, request=fake_request
        )
        assert response.status == 200
        bench.append(time.time() - t0)

    logger.info(
        f"BENCHMARK: n={len(bench)} avg={mean(bench):03f} "
        f"min={min(bench):03f} max={max(bench):03f}"
    )
    logger.info(bench)


@pytest.mark.asyncio
async def test_event(runtime, vm_pool, test_settings):
    ref = VmHash("cad11970efe9b7478300fd04d7cc91c646ca0a792b9cc718650f86e1ccfac73e")

    event = None
    result = await run_code_on_event(vm_hash=ref, event=event, pubsub=PubSub())
    assert result == {'result': 'Good'}
