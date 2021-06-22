#!/usr/bin/python3 -OO

import logging
from multiprocessing import Process

logging.basicConfig(
    level=logging.DEBUG,
    format="%(relativeCreated)4f |V %(levelname)s | %(message)s",
)
logger = logging.getLogger(__name__)

logger.debug("Imports starting")

import asyncio
import os
import socket
from enum import Enum
import subprocess
import sys
import traceback
from contextlib import redirect_stdout
from dataclasses import dataclass
from io import StringIO
from os import system
from shutil import make_archive
from typing import Optional, Dict, Any, Tuple, Iterator, List, NewType, Union

import aiohttp
import msgpack

logger.debug("Imports finished")

ASGIApplication = NewType('AsgiApplication', Any)


class Encoding(str, Enum):
    plain = "plain"
    zip = "zip"
    squashfs = "squashfs"


class Interface(str, Enum):
    asgi = "asgi"
    executable = "executable"


@dataclass
class Volume:
    mount: str
    device: str


@dataclass
class ConfigurationPayload:
    ip: Optional[str]
    route: Optional[str]
    dns_servers: List[str]
    code: bytes
    encoding: Encoding
    entrypoint: str
    input_data: bytes
    interface: Interface
    vm_hash: str
    volumes: List[Volume]
    log_level: str


@dataclass
class RunCodePayload:
    scope: Dict


# Open a socket to receive instructions from the host
server_socket = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
server_socket.bind((socket.VMADDR_CID_ANY, 52))
server_socket.listen()

# Send the host that we are ready
s0 = socket.socket(socket.AF_VSOCK, socket.SOCK_STREAM)
s0.connect((2, 52))
s0.close()

# Configure aleph-client to use the guest API
os.environ["ALEPH_API_HOST"] = "http://localhost"
os.environ["ALEPH_API_UNIX_SOCKET"] = "/tmp/socat-socket"
os.environ["ALEPH_REMOTE_CRYPTO_HOST"] = "http://localhost"
os.environ["ALEPH_REMOTE_CRYPTO_UNIX_SOCKET"] = "/tmp/socat-socket"

logger.debug("init1.py is launching")


def setup_hostname(hostname: str):
    os.environ["ALEPH_ADDRESS_TO_USE"] = hostname
    system(f"hostname {hostname}")


def setup_network(ip: Optional[str], route: Optional[str],
                  dns_servers: Optional[List[str]] = None):
    """Setup the system with info from the host."""
    dns_servers = dns_servers or []
    if not os.path.exists("/sys/class/net/eth0"):
        logger.info("No network interface eth0")
        return

    if not ip:
        logger.info("No network IP")
        return

    logger.debug("Setting up networking")
    system("ip addr add 127.0.0.1/8 dev lo brd + scope host")
    system("ip addr add ::1/128 dev lo")
    system("ip link set lo up")
    system(f"ip addr add {ip}/24 dev eth0")
    system("ip link set eth0 up")

    if route:
        system(f"ip route add default via {route} dev eth0")
        logger.debug("IP and route set")
    else:
        logger.warning("IP set with no network route")

    with open("/etc/resolv.conf", "wb") as resolvconf_fd:
        for server in dns_servers:
            resolvconf_fd.write(f"nameserver {server}\n".encode())


def setup_input_data(input_data: bytes):
    logger.debug("Extracting data")
    if input_data:
        # Unzip in /data
        if not os.path.exists("/opt/input.zip"):
            open("/opt/input.zip", "wb").write(input_data)
            os.makedirs("/data", exist_ok=True)
            os.system("unzip -q /opt/input.zip -d /data")


def setup_volumes(volumes: List[Volume]):
    for volume in volumes:
        logger.debug(f"Mounting /dev/{volume.device} on {volume.mount}")
        os.makedirs(volume.mount, exist_ok=True)
        system(f"mount -t squashfs -o ro /dev/{volume.device} {volume.mount}")
    system("mount")


def setup_code_asgi(code: bytes, encoding: Encoding, entrypoint: str) -> ASGIApplication:
    logger.debug("Extracting code")
    if encoding == Encoding.squashfs:
        sys.path.append("/opt/code")
        module_name, app_name = entrypoint.split(":", 1)
        logger.debug("import module")
        module = __import__(module_name)
        app: ASGIApplication = getattr(module, app_name)
    elif encoding == Encoding.zip:
        # Unzip in /opt and import the entrypoint from there
        if not os.path.exists("/opt/archive.zip"):
            open("/opt/archive.zip", "wb").write(code)
            logger.debug("Run unzip")
            os.system("unzip -q /opt/archive.zip -d /opt")
        sys.path.append("/opt")
        module_name, app_name = entrypoint.split(":", 1)
        logger.debug("import module")
        module = __import__(module_name)
        app: ASGIApplication = getattr(module, app_name)
    elif encoding == Encoding.plain:
        # Execute the code and extract the entrypoint
        locals: Dict[str, Any] = {}
        exec(code, globals(), locals)
        app: ASGIApplication = locals[entrypoint]
    else:
        raise ValueError(f"Unknown encoding '{encoding}'")
    return app


def setup_code_executable(code: bytes, encoding: Encoding, entrypoint: str) -> subprocess.Popen:
    logger.debug("Extracting code")
    if encoding == Encoding.squashfs:
        path = f"/opt/code/{entrypoint}"
        if not os.path.isfile(path):
            os.system("find /opt/code/")
            raise FileNotFoundError(f"No such file: {path}")
        os.system(f"chmod +x {path}")
    elif encoding == Encoding.zip:
        open("/opt/archive.zip", "wb").write(code)
        logger.debug("Run unzip")
        os.system("unzip /opt/archive.zip -d /opt")
        path = f"/opt/{entrypoint}"
        if not os.path.isfile(path):
            os.system("find /opt")
            raise FileNotFoundError(f"No such file: {path}")
        os.system(f"chmod +x {path}")
    elif encoding == Encoding.plain:
        path = f"/opt/executable {entrypoint}"
        open(path, "wb").write(code)
        os.system(f"chmod +x {path}")
    else:
        raise ValueError(f"Unknown encoding '{encoding}'. This should never happen.")

    process = subprocess.Popen(path)
    return process


def setup_code(code: bytes, encoding: Encoding, entrypoint: str, interface: Interface
               ) -> Union[ASGIApplication, subprocess.Popen]:

    if interface == Interface.asgi:
        return setup_code_asgi(code=code, encoding=encoding, entrypoint=entrypoint)
    elif interface == Interface.executable:
        return setup_code_executable(code=code, encoding=encoding, entrypoint=entrypoint)
    else:
        raise ValueError("Invalid interface. This should never happen.")


async def run_python_code_http(application: ASGIApplication, scope: dict
                               ) -> Tuple[Dict, Dict, str, Optional[bytes]]:

    logger.debug("Running code")
    with StringIO() as buf, redirect_stdout(buf):
        # Execute in the same process, saves ~20ms than a subprocess
        async def receive():
            pass

        send_queue: asyncio.Queue = asyncio.Queue()

        async def send(dico):
            await send_queue.put(dico)

        # TODO: Better error handling
        await application(scope, receive, send)
        headers: Dict = await send_queue.get()
        body: Dict = await send_queue.get()
        output = buf.getvalue()

    logger.debug("Getting output data")
    output_data: bytes
    if os.path.isdir('/data') and os.listdir('/data'):
        make_archive("/opt/output", 'zip', "/data")
        with open("/opt/output.zip", "rb") as output_zipfile:
            output_data = output_zipfile.read()
    else:
        output_data = b''

    logger.debug("Returning result")
    return headers, body, output, output_data


async def make_request(session, scope):
    async with session.request(
                scope["method"],
                url="http://localhost:8080{}".format(scope["path"]),
                params=scope["query_string"],
                headers=[(a.decode('utf-8'), b.decode('utf-8'))
                         for a, b in scope['headers']],
                data=scope.get("body", None)
            ) as resp:
        headers = {
            'headers': [(a.encode('utf-8'), b.encode('utf-8'))
                        for a, b in resp.headers.items()],
            'status': resp.status
        }
        body = {
            'body': await resp.content.read()
        }
    return headers, body


async def run_executable_http(scope: dict) -> Tuple[Dict, Dict, str, Optional[bytes]]:
    logger.debug("Calling localhost")

    tries = 0
    headers = None
    body = None

    async with aiohttp.ClientSession(conn_timeout=.05) as session:
        while not body:
            try:
                tries += 1
                headers, body = await make_request(session, scope)
            except aiohttp.ClientConnectorError:
                if tries > 20:
                    raise
                await asyncio.sleep(.05)

    output = ""
    output_data = None
    logger.debug("Returning result")
    return headers, body, output, output_data


def process_command(command: bytes, process: Process) -> Iterator[bytes]:
    if command == b"halt":
        logger.debug("Shutdown")
        system("sync")
        yield b"STOP\n"
        sys.exit()

    elif command.startswith(b"!"):
        logger.debug("Executing shell command")
        # Execute shell commands in the form `!ls /`
        msg = command[1:].decode()
        try:
            process_output = subprocess.check_output(msg, stderr=subprocess.STDOUT, shell=True)
            yield process_output
        except subprocess.CalledProcessError as error:
            yield str(error).encode() + b"\n" + error.output

    else:
        # Python'
        logger.debug("msgpack.loads (")
        msg_ = msgpack.loads(command, raw=False)
        logger.debug("msgpack.loads )")
        payload = RunCodePayload(**msg_)

        # output: Optional[str] = None
        # try:
        #     headers: Dict
        #     body: Dict
        #     output_data: Optional[bytes]
        #
        #     if interface == Interface.asgi:
        #         run_asgi_app()
        #
        #         headers, body, output, output_data = asyncio.get_event_loop().run_until_complete(
        #             run_python_code_http(application=application, scope=payload.scope)
        #         )
        #     elif interface == Interface.executable:
        #         headers, body, output, output_data = asyncio.get_event_loop().run_until_complete(
        #             run_executable_http(scope=payload.scope)
        #         )
        #     else:
        #         raise ValueError("Unknown interface. This should never happen")
        #
        #     result = {
        #         "headers": headers,
        #         "body": body,
        #         "output": output,
        #         "output_data": output_data,
        #     }
        #     yield msgpack.dumps(result, use_bin_type=True)
        # except Exception as error:
        yield msgpack.dumps({
            "error": "ERROR",
            "traceback": str(traceback.format_exc()),
            "output": b"output"
        })


def run_asgi(config: ConfigurationPayload):
    import uvicorn
    setup_code_asgi(code=config.code, encoding=config.encoding, entrypoint=config.entrypoint)
    uvicorn.run(app=config.entrypoint, host="0.0.0.0", port=8000, log_level=config.log_level.lower())


def receive_data_length(socket_client: socket.socket) -> int:
    """Receive the length of the data to follow.

    '''12
    ABCDEFGHIJKL'''
    """
    buffer = b""
    for _ in range(9):
        byte = socket_client.recv(1)
        if byte == b"\n":
            break
        else:
            buffer += byte
    return int(buffer)


def receive_config(host_socket: socket.socket) -> ConfigurationPayload:
    logger.debug("Receiving config...")
    length: int = receive_data_length(host_socket)
    data = b""
    while len(data) < length:
        data += host_socket.recv(1024 * 1024)

    logger.debug("Loading config...")
    msg_ = msgpack.loads(data, raw=False)
    msg_['volumes'] = [Volume(**volume_dict)
                       for volume_dict in msg_.get('volumes')]
    return ConfigurationPayload(**msg_)


def main():
    host, _ = server_socket.accept()
    config = receive_config(host_socket=host)

    logger.debug("Setup started...")
    setup_hostname(config.vm_hash)
    setup_volumes(config.volumes)
    setup_network(config.ip, config.route, config.dns_servers)
    setup_input_data(config.input_data)
    logger.debug("Setup finished")

    process: Union[Process, subprocess.Popen]
    try:
        if config.interface == Interface.asgi:
            process = Process(target=run_asgi, args=(config,))
            process.start()
        elif config.interface == Interface.executable:
            # process = run_executable(config)
            pass
        else:
            raise ValueError(f"Unknown interface '{config.interface}'. This should never happen.")
        host.send(msgpack.dumps({"success": True}))

    except Exception as error:
        host.send(msgpack.dumps({
            "success": False,
            "error": str(error),
            "traceback": str(traceback.format_exc()),
        }))
        logger.exception("Program could not be started")
        raise

    # Execute commands from the host
    while True:
        host, _ = server_socket.accept()
        command = host.recv(1_000_1000)  # Max 1 Mo

        logger.debug("Command received...")
        if logger.level <= logging.DEBUG:
            data_to_print = f"{command[:500]}..." if len(command) > 500 else command
            logger.debug(f"<<<\n\n{data_to_print}\n\n>>>")

        for result in process_command(command=command, process=process):
            host.send(result)

        logger.debug("Command processed")
        host.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.DEBUG)
    main()
