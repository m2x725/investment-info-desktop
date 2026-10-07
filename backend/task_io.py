"""Task-owned cancellable I/O; synchronous workflows retain a cancellable async transport."""
import asyncio
import threading
import time
from contextlib import contextmanager
import httpx
from .cancellation import JobCancelled

_context = threading.local()
NETWORK_LIMIT = threading.BoundedSemaphore(2)
PDF_LIMIT = threading.BoundedSemaphore(1)


def current_control():
    return getattr(_context, 'control', None)


@contextmanager
def bind_control(control):
    previous = current_control()
    _context.control = control
    try:
        yield
    finally:
        _context.control = previous


@contextmanager
def cancellable_lock(lock, control=None):
    control = control or current_control()
    while not lock.acquire(timeout=.1):
        if control: control.check()
    try:
        if control: control.check()
        yield
    finally:
        lock.release()


def async_request(client, method, url, control, *, max_bytes=None, **kwargs):
    control.check()
    async def perform():
        loop = asyncio.get_running_loop()
        task = asyncio.current_task()
        def cancel():
            try: loop.call_soon_threadsafe(task.cancel)
            except RuntimeError: pass
        control.register(cancel)
        transport = getattr(client, '_transport', None)
        # MockTransport supports both interfaces. Real transports are task-owned.
        transport = transport if isinstance(transport, httpx.MockTransport) else None
        try:
            async with httpx.AsyncClient(timeout=client.timeout, headers=client.headers,
                                         follow_redirects=False, transport=transport) as owned:
                if max_bytes:
                    async with owned.stream(method, url, **kwargs) as response:
                        response.raise_for_status()
                        content=bytearray()
                        async for chunk in response.aiter_bytes():
                            content.extend(chunk)
                            if len(content)>max_bytes: raise ValueError('response size limit')
                        return httpx.Response(response.status_code,headers=response.headers,
                                              content=bytes(content),request=response.request)
                return await owned.request(method,url,**kwargs)
        finally:
            control.unregister(cancel)
    try:
        # Closing a blocked synchronous socket was not a reliable cancellation mechanism.
        return asyncio.run(asyncio.wait_for(perform(),timeout=60) if max_bytes else perform())
    except asyncio.CancelledError as exc:
        if method.upper()=='POST':
            # A posted request can be billed. Preserve its reservation rather than claim zero.
            raise httpx.ReadError('task request interrupted') from exc
        raise JobCancelled() from exc


class TaskClient:
    """Wrap public source clients while preserving existing non-task callers and tests."""
    def __init__(self, client): self.client=client
    def __getattr__(self,name): return getattr(self.client,name)
    def request(self, method, url, **kwargs):
        control=current_control()
        if not control: return self.client.request(method,url,**kwargs)
        with cancellable_lock(NETWORK_LIMIT,control):
            return async_request(self.client,method,url,control,**kwargs)
    def get(self,url,**kwargs): return self.request('GET',url,**kwargs)
    def post(self,url,**kwargs): return self.request('POST',url,**kwargs)
    @contextmanager
    def stream(self,method,url,**kwargs):
        control=current_control()
        if not control:
            with self.client.stream(method,url,**kwargs) as response: yield response
        else:
            with cancellable_lock(NETWORK_LIMIT,control):
                response=async_request(self.client,method,url,control,max_bytes=32*1024*1024,**kwargs)
            yield response


def wait_process(process, timeout, control=None):
    """Check cancellation every 100ms, terminate, then kill after 500ms and reap."""
    import subprocess
    control=control or current_control()
    deadline=time.monotonic()+timeout
    try:
        while True:
            if control: control.check()
            remaining=deadline-time.monotonic()
            if remaining<=0: raise subprocess.TimeoutExpired('worker',timeout)
            try: return process.wait(timeout=min(.1,remaining))
            except subprocess.TimeoutExpired: pass
    except BaseException:
        try:
            process.terminate()
            process.wait(timeout=.5)
        except (AttributeError,subprocess.TimeoutExpired):
            process.kill();process.wait()
        raise


def set_control(control):
    _context.control=control
