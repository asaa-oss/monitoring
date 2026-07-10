import asyncio
from datetime import datetime
import json as jsonlib
from aiovk import TokenSession, API
import aiohttp
from aiovk.exceptions import  VkAPIError
import random
import time
import gc

from dotenv import load_dotenv
from os import getenv
load_dotenv()
token = getenv("TOKEN")
import random
import time
from typing import Set

# Предполагаем, что TokenSession и API импортированы из твоей библиотеки (например, vkbottle или vk_api)

class VKRealTimeManager:
    def __init__(self, token, http_session, check_interval=60):
        self.session = TokenSession(access_token=token)
        self.api = API(self.session)
        self.http_session = http_session
        self.check_interval = check_interval
        # Делаем тестовый микро-запрос для проверки связи
        
        self.tasks = {}
        self.last_posts = {}
        
        # Центральная очередь для ВСЕХ запросов к API VK
        self.vk_queue = asyncio.Queue()
        # Лимитер: 3 запроса в секунду -> пауза минимум 0.35 сек
        self.vk_rate_limit = 0.35 
        
        # Запускаем фоновый гейт, который будет дозировать запросы
        self.gate_task = asyncio.create_task(self._vk_api_gate_worker())

    async def _vk_api_gate_worker(self):
        """Единственная таска, которая имеет право дергать API VK.
        Она берет задачу из очереди, выполняет её, спит 0.35 сек и возвращает результат."""
        last_request_time = 0
        while True:
            # Получаем кортеж: (метод_api, kwargs, asyncio.Future для возврата результата)
            method, kwargs, future = await self.vk_queue.get()
            try:
                # Считаем, сколько нужно поспать, чтобы не превысить 3 запроса/сек
                now = time.time()
                elapsed = now - last_request_time
                if elapsed < self.vk_rate_limit:
                    await asyncio.sleep(self.vk_rate_limit - elapsed)
                
                # Вызываем метод (например, self.api.wall.get)
                last_request_time = time.time()
                result = await method(**kwargs)
                
                # Отдаем результат обратно в вызвавшую таску
                if not future.cancelled():
                    future.set_result(result)
            except Exception as e:
                if not future.cancelled():
                    future.set_exception(e)
            finally:
                self.vk_queue.task_done()

    async def _call_vk_safe(self, method, **kwargs):
        """Легальный и безопасный шлюз для вызова API из любой точки кода."""
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        # Кидаем запрос в очередь к единственному воркеру
        await self.vk_queue.put((method, kwargs, future))
        # Ждем, пока воркер принесет нам результат выполнения
        return await future

    async def parse_vk_id(self, link: str) -> int:
        """Преобразует ссылку или короткое имя в числовой ID группы."""
        screen_name = link.split('/')[-1]
        try:
            # Вызываем через безопасный шлюз
            response = await self._call_vk_safe(self.api.utils.resolveScreenName, screen_name=screen_name, v="5.131")
            if not response or response['type'] != 'group':
                raise ValueError(f"Ссылка {link} не ведет на группу")
            return int(response['object_id'])
        except Exception as e:
            print(f"[!] Ошибка резолва ссылки {link}: {e}")
            raise

    async def _monitor_worker(self, category, group_link):
        """Индивидуальный асинхронный цикл для каждой группы."""
        await asyncio.sleep(random.uniform(0.1, 3.0))
        try:
            group_id_raw = await self.parse_vk_id(group_link)
            owner_id = -abs(group_id_raw)
            self.last_posts[group_link] = set()

            while True:
                try:
                    # Безопасный вызов wall.get через наш гейт
                    response = await self._call_vk_safe(
                        self.api.wall.get, owner_id=owner_id, count=10, extended=1, v="5.131"
                    )
                    posts = response.get('items', [])
                

                    # Если это первый запуск — просто запоминаем текущие посты
                    if not self.last_posts[group_link]:
                        self.last_posts[group_link] = {p['id'] for p in posts}
                    if not posts:
                        await asyncio.sleep(self.check_interval)
                        continue

                    current_ids = {p['id'] for p in posts}
                    new_ids = current_ids - self.last_posts[group_link]
                    if new_ids:
                            group_info = response.get('groups', [{}])[0]
                            g_name = group_info.get('name', 'VK Group')
                            
                            for p_id in new_ids:
                                post = next((p for p in posts if p['id'] == p_id), None)
                                if not post:
                                    continue
                                
                                text = post.get('text', None)
                                post_url = f"https://vk.com/{post['owner_id']}_{post['id']}"
                                
                                print(f'[{g_name}] Найдена новая публикация!')
                                if text:
                                    payload = {
                                        "group_name": g_name,
                                        "text": text,
                                        "link": post_url,
                                        "category": category,
                                        "soc_media": "vk"
                                    }
                                    print(f"Текст: {text[:50]}...")
                                    print(f"Ссылка: {post_url}")
                                    
                                    # Отправка на твой FastAPI бэкенд локалхоста
                                    try:
                                        async with self.http_session.post("http://localhost:8000/api/inject_post", json=payload) as resp:
                                            if resp.status == 200:
                                                print("[+] Успешно инжектировано на бэкенд.")
                                    except Exception as http_err:
                                        print(f"[X] Ошибка отправки на локалхост: {http_err}")
                            
                            # Обновляем кэш постов только после обработки новых
                            self.last_posts[group_link] = current_ids

                except Exception as loop_error:
                    print(f"[!] Ошибка итерации для {group_link}: {loop_error}")
                
                # Сон строго внутри цикла while True
                await asyncio.sleep(self.check_interval)

        except asyncio.CancelledError:
            print(f"[-] Мониторинг {group_link} остановлен.")
        except Exception as e:
            print(f"[X] Критическая ошибка воркера {group_link}: {e}")

    def add_group(self, category, group_link):
        """Добавляет группу в мониторинг динамически."""
        if category not in self.tasks:
            self.tasks[category] = {}
        
        if group_link not in self.tasks[category]:
            task = asyncio.create_task(self._monitor_worker(category, group_link))
            self.tasks[category][group_link] = task

    def delete_group(self, category, group_link):
        if category in self.tasks and group_link in self.tasks[category]:
            self.tasks[category][group_link].cancel()
            del self.tasks[category][group_link]
        if group_link in self.last_posts:
            del self.last_posts[group_link]

    def remove_category(self, category):
        """Удаляет категорию и завершает все связанные задачи."""
        if category in self.tasks:
            for group_link, task in list(self.tasks[category].items()):
                task.cancel()
                if group_link in self.last_posts:
                    del self.last_posts[group_link]
            del self.tasks[category]
            print(f"[!] Категория '{category}' полностью удалена.")

    async def close(self):
        """Корректное завершение работы сессии."""
        for cat in list(self.tasks.keys()):
            self.remove_category(cat)
        self.gate_task.cancel() # Останавливаем центральный гейт
        await self.session.close()
        print("[*] Сессия ВК закрыта.")