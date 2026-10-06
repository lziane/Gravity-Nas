import asyncio
import logging
from typing import Callable

logger = logging.getLogger("GravityNAS.TaskService")

class TaskService:
    """
    A simple async task queue to handle heavy operations 
    without blocking the main thread or saturating the PI.
    """
    def __init__(self, concurrency: int = 2):
        self.queue = asyncio.Queue()
        self.concurrency = max(1, concurrency)
        self.workers = []
        self._running = False

    async def start(self):
        if self._running:
            return

        self._running = True
        for i in range(self.concurrency):
            worker = asyncio.create_task(self._worker(i))
            self.workers.append(worker)
        logger.info(f"Task Queue started with {self.concurrency} workers.")

    async def _worker(self, worker_id: int):
        while True:
            func, args, kwargs = await self.queue.get()
            try:
                if asyncio.iscoroutinefunction(func):
                    await func(*args, **kwargs)
                else:
                    await asyncio.to_thread(func, *args, **kwargs)
            except Exception as e:
                logger.error(f"Worker {worker_id} failed task: {e}")
            finally:
                self.queue.task_done()

    async def enqueue(self, func: Callable, *args, **kwargs):
        await self.queue.put((func, args, kwargs))
        logger.debug(f"Task enqueued: {func.__name__}")

    async def stop(self):
        if not self._running:
            return

        self._running = False
        for worker in self.workers:
            worker.cancel()
        await asyncio.gather(*self.workers, return_exceptions=True)
        self.workers.clear()
