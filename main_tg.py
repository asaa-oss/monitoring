import aiohttp
import ssl
import certifi
import os

os.environ['SSL_CERT_FILE'] = certifi.where()
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import re
from fastapi.middleware.cors import CORSMiddleware
from tg import client, tg_channels, parse_tg_id, tg_categories
from databases import add_link, add_category, delete_category_full, delete_single_link, load_links, get_all_data, add_post, delete_post, auto_cleanup_task
from contextlib import asynccontextmanager
import asyncio
from typing import Dict, List

session = None

@asynccontextmanager
async def lifespan(api: FastAPI):
    global client
    global session
    
    # Запускаем клиент Telethon
    await client.start()
    
    # Создаем асинхронную HTTP-сессию
    session = aiohttp.ClientSession()
    client.http_session = session
    
    # Запускаем фоновую задачу очистки БД
    cleanup_job = asyncio.create_task(auto_cleanup_task())
    
    # Загружаем ссылки из БД
    await load_links(tg_chan=tg_channels, tg_cat=tg_categories)
    
    yield
    
    # Корректно закрываем сессию, отключаем Telegram-клиент и останавливаем таски
    await session.close()
    await client.disconnect()
    cleanup_job.cancel()
    await asyncio.gather(cleanup_job, return_exceptions=True)

templates = Jinja2Templates(directory=".") 
app = FastAPI(lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class ConnectionManager:
    def __init__(self):
        # Структура: { 'it': [ws1, ws2], 'news': [ws3] }
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, category: str):
        """Вызывается при переключении вкладки на фронтенде."""
        await websocket.accept()
        
        if category not in self.active_connections:
            self.active_connections[category] = []
            
        self.active_connections[category].append(websocket)
        print(f"[WS] Юзер подключен к стриму [{category}]. Всего в этой категории: {len(self.active_connections[category])}")

    def disconnect(self, websocket: WebSocket, category: str):
        """Вызывается, когда юзер переключил вкладку или закрыл браузер."""
        if category in self.active_connections and websocket in self.active_connections[category]:
            self.active_connections[category].remove(websocket)
            print(f"[WS] Юзер отключился от категории [{category}]")
            
            # Чистим словарь, если в категории больше нет активных слушателей
            if not self.active_connections[category]:
                del self.active_connections[category]

    async def broadcast_to_category(self, message: dict, category: str):
        """Рассылает инжектированный пост ТОЛЬКО тем, кто открыл эту вкладку."""
        if category not in self.active_connections:
            return  

        # Итерируемся по копии списка категории, чтобы избежать ошибок при удалении на лету
        for connection in self.active_connections[category][:]:
            try:
                await connection.send_json(message)
            except Exception as e:
                print(f"[WS] Ошибка отправки клиенту в [{category}]: {e}")
                self.disconnect(connection, category)

manager = ConnectionManager()

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    category = websocket.query_params.get("category", "general")
    await manager.connect(websocket, category)
    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        manager.disconnect(websocket, category)

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    payload = []
    data = await get_all_data()
    for i in data:
        d = {"category": i, "links": [], "posts": []}
        payload.append(d)
    for j in data:
        for k in payload:
            if j == k["category"]:
                k["links"].append(j)
    for j in data:
        for k in payload:
            if j == k["category"]:
                d = {"soc_media": j, "group_name": j, "text": j, "link": j, "category": j}
                k["posts"].append(d)
    return templates.TemplateResponse(
        name="index.html", 
        context={"request": request, "categories": payload}
    )

@app.post("/newlink")
async def new_link(link: str, category):
    try:
        val = await add_link(link=link, category=category)
        if val == 'tg':
            rlink = await parse_tg_id(client=client, link=link)
            tg_channels.append(rlink)
            tg_categories[rlink] = category
            return {"resp": "success"}
        else:
            return {"error": "incorrect link"}
    except Exception as e:
        return {"error": f"{e}"}

@app.post("/newcategory")
async def new_category(category):
    await add_category(category=category)

@app.delete("/removecategory")
async def delete_category(category):
    await delete_category_full(category=category, tg_channels=tg_channels)

@app.delete("/removelink")
async def delete_link(link):
    await delete_single_link(link=link, tg_channels=tg_channels)

@app.post('/api/inject_post')
async def post_broadcast(post: dict):
    await manager.broadcast_to_category(message=post, category=post['category'])
    await add_post(soc_media=post['soc_media'], group_name=post['group_name'], text=post['text'], link=post['link'], category=post['category'])
