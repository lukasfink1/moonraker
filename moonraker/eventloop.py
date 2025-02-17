# Wrapper around the asyncio eventloop
#
# Copyright (C) 2021 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license

from __future__ import annotations
import asyncio
import inspect
import functools
from concurrent.futures import ThreadPoolExecutor
from typing import (
    TYPE_CHECKING,
    Awaitable,
    Callable,
    Coroutine,
    Optional,
    TypeVar,
    Union
)

if TYPE_CHECKING:
    _T = TypeVar("_T")
    FlexCallback = Callable[..., Optional[Awaitable]]
    TimerCallback = Callable[[float], Union[float, Awaitable[float]]]

class EventLoop:
    TimeoutError = asyncio.TimeoutError
    def __init__(self) -> None:
        self.aioloop = asyncio.get_event_loop()
        self.add_signal_handler = self.aioloop.add_signal_handler
        self.remove_signal_handler = self.aioloop.remove_signal_handler
        self.add_reader = self.aioloop.add_reader
        self.add_writer = self.aioloop.add_writer
        self.remove_reader = self.aioloop.remove_reader
        self.remove_writer = self.aioloop.remove_writer
        self.get_loop_time = self.aioloop.time
        self.create_future = self.aioloop.create_future
        self.create_task = self.aioloop.create_task
        self.call_at = self.aioloop.call_at
        self.set_debug = self.aioloop.set_debug

    def register_callback(self,
                          callback: FlexCallback,
                          *args,
                          **kwargs
                          ) -> None:
        if inspect.iscoroutinefunction(callback):
            self.aioloop.create_task(callback(*args, **kwargs))  # type: ignore
        else:
            self.aioloop.call_soon(
                functools.partial(callback, *args, **kwargs))

    def delay_callback(self,
                       delay: float,
                       callback: FlexCallback,
                       *args,
                       **kwargs
                       ) -> asyncio.TimerHandle:
        if inspect.iscoroutinefunction(callback):
            return self.aioloop.call_later(
                delay, self._async_callback,
                functools.partial(callback, *args, **kwargs))
        else:
            return self.aioloop.call_later(
                delay, functools.partial(callback, *args, **kwargs))

    def register_timer(self, callback: TimerCallback):
        return FlexTimer(self, callback)

    def _async_callback(self, callback: Callable[[], Coroutine]) -> None:
        # This wrapper delays creation of the coroutine object.  In the
        # event that a callback is cancelled this prevents "coroutine
        # was never awaited" warnings in asyncio
        self.aioloop.create_task(callback())

    async def run_in_thread(self,
                            callback: Callable[..., _T],
                            *args
                            ) -> _T:
        with ThreadPoolExecutor(max_workers=1) as tpe:
            return await self.aioloop.run_in_executor(tpe, callback, *args)

    def start(self):
        self.aioloop.run_forever()

    def stop(self):
        self.aioloop.stop()

    def close(self):
        self.aioloop.close()

class FlexTimer:
    def __init__(self,
                 eventloop: EventLoop,
                 callback: TimerCallback
                 ) -> None:
        self.eventloop = eventloop
        self.callback = callback
        self.timer_handle: Optional[asyncio.TimerHandle] = None
        self.running: bool = False

    def start(self, delay: float = 0.):
        if self.running:
            return
        self.running = True
        call_time = self.eventloop.get_loop_time() + delay
        self.timer_handle = self.eventloop.call_at(
            call_time, self._schedule_task)

    def stop(self):
        if not self.running:
            return
        self.running = False
        if self.timer_handle is not None:
            self.timer_handle.cancel()
            self.timer_handle = None

    def _schedule_task(self):
        self.timer_handle = None
        self.eventloop.create_task(self._call_wrapper())

    def is_running(self) -> bool:
        return self.running

    async def _call_wrapper(self):
        if not self.running:
            return
        ret = self.callback(self.eventloop.get_loop_time())
        if isinstance(ret, Awaitable):
            ret = await ret
        if self.running:
            self.timer_handle = self.eventloop.call_at(ret, self._schedule_task)
