import asyncio
from connection import Connection
from asyncioutil import *
import logging

logger = logging.getLogger(__name__)


SUPPORTED_VERSIONS = [1]

class Server:

    def __init__(self, host, port, handler):
        self.host = host
        self.port = port
        self.handler = handler
        self.active_connections = 0
        self.max_connections = 100  # 设置最大连接数
        self.connection_semaphore = asyncio.Semaphore(self.max_connections)

    async def handle_client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        addr = writer.get_extra_info('peername')
        
        # 检查连接数是否超过限制
        if self.active_connections >= self.max_connections:
            logger.warning(f"Connection limit reached, rejecting connection from {addr}")
            writer.close()
            await writer.wait_closed()
            return
        
        # 获取连接信号量
        async with self.connection_semaphore:
            self.active_connections += 1
            logger.info(f"Connected client from {addr}, active connections: {self.active_connections}")
            
            try:
                # 读取客户端版本
                try:
                    client_version = (await asyncio.wait_for(reader.readexactly(1), timeout=10))[0]
                    logger.info(f"Client version: {client_version} from {addr}")
                except asyncio.TimeoutError:
                    logger.warning(f"Timeout waiting for client version from {addr}")
                    writer.close()
                    await writer.wait_closed()
                    return
                except (asyncio.IncompleteReadError, ConnectionResetError):
                    logger.info(f"Client disconnected during version handshake from {addr}")
                    writer.close()
                    await writer.wait_closed()
                    return

                if client_version not in SUPPORTED_VERSIONS:
                    logger.warning(f"Unsupported protocol version: {client_version} from {addr}")
                    writer.close()
                    await writer.wait_closed()
                    return

                connection = Connection(writer)

                try:
                    self.handler(connection)
                    while True:
                        try:
                            data = await asyncio.wait_for(receive_message(reader), timeout=300)  # 5分钟超时
                            connection.on_receive(data)
                        except asyncio.TimeoutError:
                            logger.warning(f"Client {addr} timeout, closing connection")
                            break
                except (asyncio.IncompleteReadError, ConnectionResetError):
                    logger.info(f"Client disconnected from {addr}")
                except Exception as e:
                    logger.error(f"Error handling client {addr}: {e}")
                finally:
                    connection.close()
            finally:
                self.active_connections -= 1
                logger.info(f"Client connection closed from {addr}, active connections: {self.active_connections}")

    async def start(self):
        server = await asyncio.start_server(self.handle_client, self.host, self.port)
        addrs = ', '.join(str(sock.getsockname()) for sock in server.sockets)
        logger.info(f"Server listening on {addrs}, max connections: {self.max_connections}")
        async with server:
            await server.serve_forever()
            