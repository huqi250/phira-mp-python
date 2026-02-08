# 修改 connection.py
import asyncio
import logging

from asyncioutil import write_message
from rymc.phira.protocol import PacketRegistry
from rymc.phira.protocol.util import ByteBuf

logger = logging.getLogger(__name__)

class Connection:
    def __init__(self, writer: asyncio.StreamWriter):
        self.writer = writer
        self.receiver = None
        self.closeHandler = None
        self.connected = True
        self.last_activity = asyncio.get_event_loop().time()
        # 【新增】创建一个队列来管理发送任务
        self.write_queue = asyncio.Queue(maxsize=100)  # 设置队列最大容量
        # 【新增】启动一个后台任务专门负责发送
        self._sender_task = asyncio.create_task(self._send_loop())
        # 【新增】启动连接健康检查
        self._health_check_task = asyncio.create_task(self._health_check())

    # 【新增】发送循环，确保同一时间只有一个包写入 Socket
    async def _send_loop(self):
        try:
            while self.connected:
                # 等待队列中有数据
                try:
                    data = await asyncio.wait_for(self.write_queue.get(), timeout=5)
                    # 更新最后活动时间
                    self.last_activity = asyncio.get_event_loop().time()
                    # 写数据 (此时是串行的，不会冲突)
                    try:
                        await write_message(self.writer, data)
                    except Exception as e:
                        logger.error(f"Error writing to socket: {e}")
                        self.connected = False
                        self.close()
                        break
                    finally:
                        self.write_queue.task_done()
                except asyncio.TimeoutError:
                    # 超时，检查连接状态
                    continue
                except asyncio.CancelledError:
                    break
        except asyncio.CancelledError:
            pass  # 任务被取消，正常退出
        except Exception as e:
            logger.error(f"Error in send loop: {e}")
            self.close()

    # 【新增】连接健康检查
    async def _health_check(self):
        try:
            while self.connected:
                await asyncio.sleep(30)  # 每30秒检查一次
                current_time = asyncio.get_event_loop().time()
                # 检查是否超过2分钟没有活动
                if current_time - self.last_activity > 120:
                    logger.warning("Connection inactive for too long, closing...")
                    self.close()
                    break
        except asyncio.CancelledError:
            pass  # 任务被取消，正常退出
        except Exception as e:
            logger.error(f"Error in health check: {e}")

    def send(self, packet):
        try:
            if not self.connected:
                logger.warning("Attempting to send packet on closed connection")
                return False
            
            data = PacketRegistry.encode(packet).toBytes()
            if data[0] != 0x00:
                logger.debug(f"Send packet: {data.hex()}")
            
            # 【修改】不再创建新任务，而是放入队列
            try:
                self.write_queue.put_nowait(data)
                return True
            except asyncio.QueueFull:
                logger.error("Send queue full, packet dropped")
                return False
        except Exception as e:
            logger.error(f"Failed to enqueue packet: {e}")
            return False

    def set_receiver(self, receiver):
        self.receiver = receiver

    def on_receive(self, data):
        if data[0] != 0x00:
            logger.debug(f"Receive packet: {data.hex()}")
        if self.receiver is None:
            return
        # 更新最后活动时间
        self.last_activity = asyncio.get_event_loop().time()
        try:
            self.receiver(PacketRegistry.decode(ByteBuf(data)))
        except Exception as e:
            logger.error(f"Error processing received packet: {e}")

    def is_closed(self):
        return not self.connected or self.writer.is_closing()

    def close(self):
        if not self.connected:
            return
        
        self.connected = False
        # 【新增】关闭连接时取消发送任务和健康检查任务
        if self._sender_task:
            self._sender_task.cancel()
        if self._health_check_task:
            self._health_check_task.cancel()
        asyncio.create_task(self.close_and_wait())

    async def close_and_wait(self, writer_timeout: float = 2) -> None:
        if self.writer is None:
            return
        try:
            if not self.writer.is_closing():
                await asyncio.wait_for(self.writer.drain(), timeout=writer_timeout)
        except Exception:
            pass
        try:
            self.writer.close()
            await asyncio.wait_for(self.writer.wait_closed(), timeout=writer_timeout)
        except Exception:
            pass
        self.writer = None
        if self.closeHandler:
            try:
                self.closeHandler()
            except Exception as e:
                logger.error(f'[Connection] closeHandler exception: {e}')

    def on_close(self, close_handler):
        self.closeHandler = close_handler