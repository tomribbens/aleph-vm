import asyncio
import logging

from aiohttp.test_utils import make_mocked_request

from vm_supervisor.supervisor import run_code
from vm_supervisor.conf import settings


def test_run_code():
    settings.update(
        PRINT_SYSTEM_LOGS=True,
        USE_JAILER=False,
    )


    request = make_mocked_request('GET', '/run/fastapi/run/placeholder',
                                  match_info={'code_id': 'fastapi',
                                              'suffix': '/run/placeholder'})
    loop = asyncio.get_event_loop()
    resp = loop.run_until_complete(run_code(request))
    assert resp.body == b'{"output": "{\\"item_id\\":\\"placeholder\\",\\"q\\":null}"}'


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    test_run_code()
