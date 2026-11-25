"""Render bepul Web Service uchun: kichik HTTP server va o'zini uyg'otib turish.

Render bepul web service 15 daqiqa kiruvchi trafik bo'lmasa uxlatib qo'yadi.
Bot esa long polling bilan ishlagani uchun tashqaridan so'rov kelmaydi, shuning uchun
har PING_INTERVAL soniyada (standart 600 = 10 daqiqa) o'zining ommaviy manziliga
so'rov yuboramiz.
"""
import asyncio
import logging
import os

import aiohttp
from aiohttp import web

PING_INTERVAL = int(os.getenv("PING_INTERVAL", "600"))


async def _ok(request: web.Request) -> web.Response:
    return web.Response(text="ok")


async def start_server() -> web.AppRunner:
    app = web.Application()
    app.router.add_get("/", _ok)
    app.router.add_get("/health", _ok)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    logging.info("HTTP server %s portda ishga tushdi", port)
    return runner


async def ping_loop() -> None:
    url = os.getenv("RENDER_EXTERNAL_URL")
    if not url:
        logging.info("RENDER_EXTERNAL_URL yo'q: o'zini uyg'otish o'chirilgan (lokal ishga tushirish)")
        return
    target = url.rstrip("/") + "/health"
    timeout = aiohttp.ClientTimeout(total=30)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        while True:
            await asyncio.sleep(PING_INTERVAL)
            try:
                async with session.get(target) as resp:
                    logging.info("keep-alive ping %s -> %s", target, resp.status)
            except Exception as e:
                logging.warning("keep-alive ping xatosi: %s", e)
