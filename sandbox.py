#!/usr/bin/env python3

# Copyright (C) 2016 Lukas Rist
#
# This program is free software; you can redistribute it and/or
# modify it under the terms of the GNU General Public License
# as published by the Free Software Foundation; either version 2
# of the License, or (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.

import os
import tempfile
import json
import asyncio
from aiohttp import web
from asyncio.subprocess import PIPE

from pprint import pprint

import analysis


class PHPSandbox(object):

    def __init__(self, pre=os.getcwd() + '/', debug_level=0):
        self.pre = pre

    @classmethod
    def php_tag_check(cls, script):
        with open(script, "r+") as check_file:
            file_content = check_file.read()
            if "<?" not in file_content:
                file_content = "<?php" + file_content
            if "?>" not in file_content:
                file_content += "?>"
            check_file.write(file_content)
        return script

    @asyncio.coroutine
    def read_process(self):
        while True:
            line = yield from self.proc.stdout.readline()
            if not line:
                break
            else:
                self.stdout_value += line

    @asyncio.coroutine
    def sandbox(self, script):
        if not os.path.isfile(script):
            raise Exception("Sample not found: {0}".format(script))

        try:
            cmd = ["php5", self.pre + "sandbox.php", script]
            self.proc = yield from asyncio.create_subprocess_exec(*cmd, stdout=PIPE)
            self.stdout_value = b''
            yield from asyncio.wait_for(self.read_process(), timeout=3)
        except Exception as e:
            try:
                self.proc.kill()
            except Exception:
                pass
            print("Error executing the sandbox: {}".format(e))
            # raise e

        analyzer = analysis.DataAnalysis(script)
        self.botnet = analyzer.analyze(self.stdout_value)
        print("Parsed with sandbox")
        pprint(self.botnet.todict())
        return self.botnet


class EchoServer(asyncio.Protocol):
    def connection_made(self, transport):
        # peername = transport.get_extra_info('peername')
        # print('connection from {}'.format(peername))
        self.transport = transport

    def data_received(self, data):
        # print('data received: {}'.format(data.decode()))
        self.transport.write(data)


@asyncio.coroutine
def api(request):
    data = yield from request.payload.read()
    with tempfile.NamedTemporaryFile(suffix='.php') as f:
        f.write(data)
        f.seek(0)
        sb = PHPSandbox()
        try:
            server = yield from loop.create_server(EchoServer, '127.0.0.1', 1234)
            yield from asyncio.wait_for(sb.sandbox(f.name), timeout=10)
            server.close()
        except KeyboardInterrupt:
            pass
        return web.Response(body=json.dumps(sb.botnet.todict(), sort_keys=True, indent=4).encode('utf-8'))


if __name__ == '__main__':
    app = web.Application()
    app.router.add_route('POST', '/', api)

    loop = asyncio.get_event_loop()
    handler = app.make_handler()
    f = loop.create_server(handler, '0.0.0.0', 8080)
    srv = loop.run_until_complete(f)
    print('serving on', srv.sockets[0].getsockname())
    try:
        loop.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        loop.run_until_complete(handler.finish_connections(1.0))
        srv.close()
        loop.run_until_complete(srv.wait_closed())
        loop.run_until_complete(app.finish())
    loop.close()
