import aiohttp
import ssl
import certifi
import os

os.environ['SSL_CERT_FILE'] = certifi.where()
from fastapi import FastAPI, Request, Depends, WebSocket, WebSocketDisconnect
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
import re
from fastapi.middleware.cors import CORSMiddleware
from vk2 import VKRealTimeManager, token
from databases_vk import add_link, add_category, delete_category_full, delete_single_link, load_links, get_all_data, add_post, delete_post, auto_cleanup_task
from contextlib import asynccontextmanager
import asyncio
from typing import Dict, List

session = None

@asynccontextmanager
async def lifespan(api: FastAPI):
    cleanup_job = asyncio.create_task(auto_cleanup_task())
    session = aiohttp.ClientSession()
    vkman = VKRealTimeManager(token=token, http_session=session)
    app.state.vkman = vkman
    
    # Загружаем ссылки только для VK менеджера
    await load_links(vk=vkman)
    yield
    await vkman.close()
    await session.close()
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
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, websocket: WebSocket, category: str):
        await websocket.accept()
        if category not in self.active_connections:
            self.active_connections[category] = []
        self.active_connections[category].append(websocket)
        print(f"[WS] Юзер подключен к стриму [{category}]. Всего в этой категории: {len(self.active_connections[category])}")

    def disconnect(self, websocket: WebSocket, category: str):
        if category in self.active_connections and websocket in self.active_connections[category]:
            self.active_connections[category].remove(websocket)
            print(f"[WS] Юзер отключился от категории [{category}]")
            if not self.active_connections[category]:
                del self.active_connections[category]

    async def broadcast_to_category(self, message: dict, category: str):
        if category not in self.active_connections:
            return  
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
    for i in data[0]:
        d = {"category": i[0], "links": [], "posts": []}
        payload.append(d)
    for j in data[1]:
        for k in payload:
            if j[1] == k["category"]:
                k["links"].append(j[0])
    for j in data[2]:
        for k in payload:
            if j[4] == k["category"]:
                d = {"soc_media": j[0], "group_name": j[1], "text": j[2], "link": j[3], "category": j[4]}
                k["posts"].append(d)
    return templates.TemplateResponse(
        name="index.html", 
        context={"request": request, "categories": payload}
    )
    
def get_vkman(request: Request):
    try:
        return request.app.state.vkman
    except Exception:
        return None

@app.post("/newlink")
async def new_link(link: str, category, vkman=Depends(get_vkman)):
    try:
        val = await add_link(link=link, category=category)
        if val == 'vk':
            vkman.add_group(category=category, group_link=link)
            return {"resp": "success"}
        else:
            return {"error": "incorrect link"}
    except Exception as e:
        return {"error": f"{e}"}

@app.post("/newcategory")
async def new_category(category):
    await add_category(category=category)

@app.delete("/removecategory")
async def delete_category(category, vkman=Depends(get_vkman)):
    # Из вызова удален tg_channels
    await delete_category_full(category=category, vk_manager=vkman)

@app.delete("/removelink")
async def delete_link(link, vkman=Depends(get_vkman)):
    # Из вызова удален tg_channels
    await delete_single_link(link=link, vk_manager=vkman)

@app.post('/api/inject_post')
async def post_broadcast(post: dict):
    await manager.broadcast_to_category(message=post, category=post['category'])
    await add_post(soc_media=post['soc_media'], group_name=post['group_name'], text=post['text'], link=post['link'], category=post['category'])
