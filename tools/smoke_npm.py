"""Exercise an unpacked npm CLI through the real MCP SDK, without WeChat."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import tarfile
import tempfile

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


async def check(node, archive, native=False):
    with tempfile.TemporaryDirectory(prefix='weSkill npm smoke ') as directory:
        folder = Path(directory)
        with tarfile.open(archive) as tar:
            tar.extractall(folder, filter='data')
        cli = folder / 'package/bin/weskill.mjs'
        version = json.loads((folder/'package/package.json').read_text())['version']
        args = [str(cli), 'mcp', *([] if native else ['--diagnostics']),
                '--data-dir', str(folder / 'user data')]
        params = StdioServerParameters(command=node, args=args, env={**os.environ})
        # Includes the first-run Python bootstrap. It must keep stdout clean.
        async with asyncio.timeout(180):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    assert init.serverInfo.name == 'weskill'
                    listing = await session.list_tools()
                    if native:
                        assert len(listing.tools) == 31
                    else:
                        assert {x.name for x in listing.tools} == {'get_client_identity', 'get_capabilities'}
                    result = await session.call_tool('get_capabilities', {})
                    assert not result.isError
                    assert result.structuredContent['toolbox_version'] == version
                    assert result.structuredContent['business_operations_available'] is native
        # No bootstrap on the second start, including without pip/network.
        async with asyncio.timeout(30):
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    assert len((await session.list_tools()).tools) == (31 if native else 2)
        print('PASS: packed npm CLI bootstraps Python and passes real MCP handshake twice')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive', type=Path)
    parser.add_argument('--node', default='node')
    parser.add_argument('--native', action='store_true')
    options = parser.parse_args()
    asyncio.run(check(options.node, options.archive, options.native))
