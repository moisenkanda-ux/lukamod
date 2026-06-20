import asyncio
import json
import socket
import aiohttp
import time
from typing import Dict, Optional

SERVER_ADDR = "0.0.0.0"
SERVER_PORT = 8080
BUFFER_SIZE = 8192 * 8
TARGET_PORT_SSH = 22
TARGET_PORT_WS = 8080
API_URL = "https://pastebin.com/raw/sxEzn2Jr"

class Target:
    def __init__(self, addr: str, port: int, ws: bool):
        self.addr = addr
        self.port = port
        self.ws = ws

class IPs:
    def __init__(self, **kwargs):
        self.default = kwargs.get("default", "")
        
        self.app = {f"app{i}": kwargs.get(f"app{i}", "") for i in range(1, 251)}

    def get_ip(self, endpoint: str) -> str:

        if endpoint.startswith("/ws") and endpoint.endswith("/"):
            index = endpoint.strip("/ws/")
            return self.app.get(f"app{index}", self.default)
        
        elif endpoint.startswith("/app"):
            index = endpoint.strip("/app")
            return self.app.get(f"app{index}", self.default)
        
        return self.default

ip_data = IPs()
ip_data_lock = asyncio.Lock()

async def fetch_ips():
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(API_URL) as resp:
                    data = await resp.json()
                    async with ip_data_lock:
                        global ip_data
                        ip_data = IPs(**data)
        except Exception as e:
            print(f"Failed to fetch IPs: {e}")
        await asyncio.sleep(60)

def create_target(endpoint: str) -> Optional[Target]:
    global ip_data

    addr = ip_data.get_ip(endpoint)

    if endpoint.startswith("/ws") and endpoint.endswith("/"):
        return Target(addr=addr, port=TARGET_PORT_WS, ws=True)
    
    elif endpoint.startswith("/app"):
        return Target(addr=addr, port=TARGET_PORT_SSH, ws=False)

    return Target(addr=ip_data.default, port=TARGET_PORT_SSH, ws=False)

async def handle_client(client_reader, client_writer):
    addr = client_writer.get_extra_info('peername')
    print(f"Connected to client: {addr}")

    data = await client_reader.read(BUFFER_SIZE)
    if not data:
        return

    payload = data.decode()
    endpoint = payload.split(" ")[1]
    target = create_target(endpoint)
    if not target:
        print(f"Invalid endpoint: {payload}")
        return

    try:
        reader, writer = await asyncio.open_connection(target.addr, target.port)
    except Exception as e:
        print(f"Failed to connect to target: {e}")
        return

    if target.ws:
        writer.write(data)
        await writer.drain()
    else:
        client_writer.write(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: Websocket\r\nConnection: Upgrade\r\n\r\n")
        await client_writer.drain()

    async def forward(src, dst):
        try:
            while True:
                data = await src.read(BUFFER_SIZE)
                if not data:
                    break
                dst.write(data)
                await dst.drain()
        except Exception as e:
            print(f"Error forwarding data: {e}")
        finally:
            dst.close()

    await asyncio.gather(
        forward(client_reader, writer),
        forward(reader, client_writer)
    )

async def main():
    asyncio.create_task(fetch_ips())

    server = await asyncio.start_server(handle_client, SERVER_ADDR, SERVER_PORT)
    addr = server.sockets[0].getsockname()
    print(f"Server is listening on {addr}")

    async with server:
        await server.serve_forever()

if __name__ == "__main__":
    asyncio.run(main())