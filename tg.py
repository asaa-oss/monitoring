from telethon import TelegramClient, events
from telethon.network.connection import ConnectionTcpMTProxyAbridged
from telethon.tl.types import PeerChannel
import asyncio
import binascii
import datetime
from dotenv import load_dotenv
import json as jsonlib
from os import getenv
tg_categories = {}
load_dotenv()
api_id = getenv("api_id")
api_hash = getenv("api_hash")
tg_channels = []
client = TelegramClient('monitoring_session', api_id, api_hash)
async def parse_tg_id(client:TelegramClient,link:str):
    id = link.split("#")[-1].lstrip('-')
    if id.isdigit():
        ent = await client.get_entity(PeerChannel(int(id)))
    else:
        ent = await client.get_entity(id)
    return ent.id
@client.on(events.NewMessage())
async def handler(event):
    if event.message.date < datetime.datetime.now(datetime.timezone.utc):
        return
    if event.chat.id not in tg_channels:
        return
    # event.message содержит всю информацию о новом посте
    print(f"Новое сообщение в канале {event.chat.title}:")
    print(event.message.text)
    json = {"group_name":event.chat.title,"text":event.message.text,"link":f"https://t.me/c/{event.chat.id}/{event.id}","category":tg_categories[event.chat.id],"soc_media":"tg"}
    try:
        async with client.http_session.post(f"http://localhost:8000/api/inject_post?", json=json) as response:
            pass
    except Exception as e:
        print(f"Ошибка отправки: {e}")
    

async def main():
    await client.start()
    # "Просим" Telegram дать информацию о каналах, чтобы активировать мониторинг
    for channel in tg_channels:
        await client.get_entity(channel)
    print("Сущности обновлены, мониторинг активен.")
    await client.run_until_disconnected()
if __name__ == "__main__":
    asyncio.run(main())