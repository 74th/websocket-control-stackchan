from vvclient import Client as VVClient
import asyncio

def create_voicevox_client() -> VVClient:
    return VVClient(base_uri="http://localhost:50021")


async def main():
    async with create_voicevox_client() as client:
        audio_query = await client.create_audio_query(
            "こんにちは。今日も良い天気ですね。こんにちは。今日も良い天気ですね。こんにちは。今日も良い天気ですね。こんにちは。今日も良い天気ですね。こんにちは。今日も良い天気ですね。", speaker=29
        )
        with open("recordings/voice.wav", "wb") as f:
            f.write(await audio_query.synthesis(speaker=29))


if __name__ == "__main__":
    asyncio.run(main())
