# Описание проекта

## 1. Настройки подключения (Секретные ключи)

Для работы скрипта создайте файл `.env` в корневой папке и добавьте туда ваши доступы:

```env
# ВКонтакте (VK)
TOKEN=ваш_токен_доступа

# Telegram (my.telegram.org)
api_id=ваш_api_id
api_hash=ваш_api_hash
```

---
апи айди и апи хеш получить из my.telegram.org. аккуратно сайт капризный.  токен доступа вк можно на сайте vkhost.github.io / в поле scope при переходе указать wall,offline

## 2. Структура базы данных

запросы для создания ссылки в файле links.db. если называешь по другому - в databases поменяй название файла .db
CREATE TABLE categories(
        category text
);
CREATE TABLE links(
 soc_media CHAR(2),
 url TEXT,
 category TEXT
 );
 CREATE TABLE posts(
id INTEGER  PRIMARY KEY AUTOINCREMENT,
soc_media TEXT,
group_name TEXT,
text TEXT,
link TEXT,
category text,
created_at TEXT DEFAULT CURRENT_TIMESTAMP
);


---

## 3. Генерация прямых ссылок на посты

При выводе постов из базы данных полные ссылки собираются по следующим правилам:

* **ВКонтакте:** `https://vk.com` + `group_id` + `_` + `post_id`
* **Telegram:** `https://t.me` +'/c/' `group_id` + `/` + `post_id`

## примечание 
фронтенд в вске будет подсвечивать ошибку - не реагировать. все работает ошибка это просто  особенность jinja. перед запуском самой проги запусти сначала файл tg.py - в терминале попросит написать данные для тг акка. это чтобы создать файл .session  и он уже дальше запоминал сессию.