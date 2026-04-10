import asyncio
import websockets
import json

async def main():
    url = "wss://badi-public.crowdmonitor.ch:9591/api"
    async with websockets.connect(url) as ws:
        msg = await ws.recv()
        try:
            data = json.loads(msg)
            for loc in data:
                print(f"{loc.get('name')}: {loc.get('uid')}")
        except Exception as e:
            print("Error parsing message:", e)

if __name__ == "__main__":
    asyncio.run(main())
