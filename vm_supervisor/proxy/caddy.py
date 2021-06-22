from base64 import b32encode, b16decode

import aiohttp

from .abstract import ProxyConfigurator

DOMAIN = "vm.demo.okeso.fr"
CADDY_API_URL = "http://127.0.0.1:2019/"


def caddy_new_route(host: str, upstream: str, uid: str):
    return {
        "handle": [
            {
                "handler": "subroute",
                "routes": [
                    {
                        "handle": [
                            {
                                "@id": f"subroute-{uid}",
                                "handler": "reverse_proxy",
                                "headers": {
                                    "request": {
                                        "set": {
                                            "Host": [
                                                "{http.request.host}"
                                            ]
                                        }
                                    }
                                },
                                "upstreams": [
                                    {
                                        "dial": upstream
                                    }
                                ]
                            }
                        ]
                    }
                ]
            }
        ],
        "match": [
            {
                "host": [
                    host
                ]
            }
        ],
        "terminal": True
    }


def b16_to_b32(hash: str) -> bytes:
    """Convert base32 encoded bytes to base16 encoded bytes."""
    return b32encode(b16decode(hash.upper())).lower().strip(b'=')


class CaddyProxy(ProxyConfigurator):
    """Caddy Server configurator.
    """

    async def register_uid(self, uid: str, upstream: str = "127.0.0.1:8080"):
        uid_base32 = b16_to_b32(uid).decode()
        host = f"{uid_base32}.{DOMAIN}"
        config = caddy_new_route(host=host, upstream=upstream, uid=uid)
        url = CADDY_API_URL + "config/apps/http/servers/srv0/routes/0"

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(10)) as session:
            async with session.put(url, json=config) as response:
                response.raise_for_status()
                print("OK")
