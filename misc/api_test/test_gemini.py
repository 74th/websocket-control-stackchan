import asyncio
from google import genai
from google.genai import types

MODEL = "gemini-3-flash-preview"

async def main() -> None:
    client = genai.Client(vertexai=True)

    chat = client.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction="あなたは親切な音声アシスタントです。音声で返答するため、マークダウンは記述せず、簡潔に答えてください。だいたい3文程度で答えてください。",
        ),
    )

    text = "スタックチャンとはどういうムーブメントか知ってる？"

    resp = await asyncio.to_thread(chat.send_message, text)

    answer = resp.text

    print("AIの回答:", answer)

    text = "より詳しく教えて"

    resp = await asyncio.to_thread(chat.send_message, text)

    print("AIの回答:", answer)

if __name__ == "__main__":
    asyncio.run(main())
