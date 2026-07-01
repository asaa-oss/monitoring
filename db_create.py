import asyncio
import aiosqlite


db  = 'h.db'
async def create_db():
    async with aiosqlite.connect(db) as conn:
          await conn.execute('CREATE TABLE categories(category text)')
          await conn.execute("""CREATE TABLE links(
                               soc_media CHAR(2),
                              url TEXT,
                             category TEXT)""")
          await conn.execute("""CREATE TABLE posts(
                               id INTEGER PRIMARY KEY AUTOINCREMENT,
                              soc_media TEXT,
                              group_name TEXT,
                              text TEXT,
                              link TEXT,
                             category TEXT,
                              created_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
          await conn.commit()
asyncio.run(create_db())