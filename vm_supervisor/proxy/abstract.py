
from abc import abstractmethod


class ProxyConfigurator:
    """Configures a reverse-proxy that forwards client connections to the right VM
    over the internal/local network.
    """

    @abstractmethod
    async def register_uid(self, uid: str, ip: str):
        ...
