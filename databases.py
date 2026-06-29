import aiosqlite
import re
import asyncio
from tg import parse_tg_id,client
from aiovk import TokenSession,API
from vk2 import VKRealTimeManager
from dotenv import load_dotenv
DB_FILE = 'links.db'
TOKEN = load_dotenv("TOKEN")
async def load_links(vk:VKRealTimeManager,tg_chan:list,tg_cat:dict):
    conn = await aiosqlite.connect(DB_FILE)
    async with conn.execute("SELECT * from links") as cursor:
        rows = await cursor.fetchall()
        for row in rows:
            if row[0] == 'tg':
                d = await parse_tg_id(client,row[1])
                tg_chan.append(d)
                tg_cat[d] = row[2]
            elif row[0] == 'vk':
                vk.add_group(row[2],row[1])
    await conn.close()
    
async def add_link(link:str,category):
    tg_pattern = r"(https?://)?(t\.me|telegram\.me|web\.telegram\.org)/[a-zA-Z0-9_\+]+"
    vk_pattern = r"(https?://)?(vk\.com|vk\.ru)/[a-zA-Z0-9._]+"

    if re.search(tg_pattern, link):
        conn =   await aiosqlite.connect(DB_FILE)
        await conn.execute("INSERT INTO links(soc_media,url,category) VALUES(?,?,?)",("tg",link,category))
        await conn.commit()
        await conn.close()
        return 'tg'
    elif re.search(vk_pattern, link):
        conn =  await aiosqlite.connect(DB_FILE)
        await conn.execute("INSERT INTO links(soc_media,url,category) VALUES(?,?,?)",("vk",link,category))
        await conn.commit()
        await conn.close()
        return 'vk'
    else:
        return "incorrect link"
async def add_category(category):
    conn =   await aiosqlite.connect(DB_FILE)
    await conn.execute("INSERT INTO categories(category) VALUES(?)",(category,))
    await conn.commit()
    await conn.close()

async def delete_category_full(category, tg_channels: list, vk_manager):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Получаем все ссылки этой категории перед удалением
        async with db.execute(
            "SELECT url, soc_media FROM links WHERE category = ?", 
            (category,)
        ) as cursor:
            links = await cursor.fetchall()

        # 2. Выводим каждую ссылку из мониторинга
        for link in links:
            link_url = link["url"]
            
            if link["soc_media"] == "tg":
                if link_url in tg_channels:
                    tg_channels.remove(link_url)
            
            elif link["soc_media"] == "vk":
                # Вызываем метод вашего класса
                await vk_manager.remove_category(link_url)

        # 3. Удаляем данные из БД (сначала ссылки, потом категорию)
        await db.execute("DELETE FROM posts where category = ?",(category,))
        await db.execute("DELETE FROM links WHERE category = ?", (category,))
        await db.execute("DELETE FROM categories WHERE category = ?", (category,))
        
        await db.commit()
async def delete_single_link(link:str, tg_channels: list, vk_manager):
    async with aiosqlite.connect(DB_FILE) as db:
        db.row_factory = aiosqlite.Row
        
        # 1. Находим инфо о ссылке, чтобы понять, откуда её удалять
        async with db.execute(
            "SELECT url, soc_media FROM links WHERE url = ?", (link,)
        ) as cursor:
            link = await cursor.fetchone()
        
        if link:
            link_url = link["url"]
            
            # 2. Удаляем из оперативной памяти
            if link["soc_media"] == "tg":
                if link_url in tg_channels:
                    tg_channels.remove(link_url)
            
            elif link["soc_media"] == "vk":
                await vk_manager.delete_group(link_url)

            # 3. Удаляем из БД
            await db.execute("DELETE FROM posts where link = ?",(link,))
            await db.execute("DELETE FROM links WHERE url = ?", (link,))
            await db.commit()
async def add_post(soc_media,group_name,text,link,category):
    db = await aiosqlite.connect(DB_FILE)
    await db.execute("INSERT INTO posts(soc_media,group_name,text,link,category) VALUES (?,?,?,?,?)",(soc_media,group_name,text,link,category))
    await db.commit()
    await db.close()
async def get_all_data():
    db = await aiosqlite.connect(DB_FILE)
    categories = await db.execute_fetchall("SELECT * FROM Categories")
    links = await db.execute_fetchall("SELECT url,category FROM links")
    posts = await db.execute_fetchall("SELECT soc_media, group_name, text, link, category FROM posts order by id desc")
    await db.commit()
    await db.close()
    return categories,links,posts
async def delete_post(soc_media,group_name,text,link,category):
    db =  await aiosqlite.connect(DB_FILE)
    await db.execute("DELETE FROM posts where soc_media= ? and group_name = ? and text = ? and link = ? and category = ? ",(soc_media,group_name,text,link,category))
    await db.commit()
    await db.close()
async def auto_cleanup_task():
    """Фоновая задача: раз в сутки удаляет посты старше 30 дней и сжимает БД"""
    print("[БД-Очистка] Фоновый таск успешно запущен в lifespan.")
    try:
        while True:
            try:
                # Подключаемся к SQLite асинхронно
                async with aiosqlite.connect(DB_FILE) as db:
                    # 1. Удаляем посты, которые были созданы более 30 дней назад
                    async with db.execute("""
                        DELETE FROM posts 
                        WHERE created_at < DATETIME('now', '-30 days');
                    """) as cursor:
                        deleted_rows = cursor.rowcount
                    
                    await db.commit()
                    if deleted_rows > 0:
                        print(f"[БД-Очистка] Удалено устаревших постов: {deleted_rows}")
                    
                    # 2. Сжимаем файл БД на диске, освобождая место для ОС
                    await db.execute("VACUUM;")
                    print("[БД-Очистка] Сжатие файла (VACUUM) выполнено.")
                    
            except Exception as e:
                print(f"[БД-Очистка] Ошибка при выполнении клинапа: {e}")
            
            # Засыпаем строго на 24 часа (24 часа * 60 минут * 60 секунд)
            await asyncio.sleep(86400)
            
    except asyncio.CancelledError:
        print("[БД-Очистка] Фоновый таск корректно остановлен вместе с сервером.")