# Фінальне завдання

HTTP-сервер на :3000 (маршрути, статика, форма) + Socket-сервер (TCP) на :5000, 
який приймає JSON і зберігає повідомлення в MongoDB.

## Структура

goit-cs-hw-06/
├─ main.py
├─ templates/
│ ├─ index.html
│ ├─ message.html
│ └─ error.html
├─ static/
│ ├─ style.css
│ └─ logo.png
├─ Dockerfile
├─ docker-compose.yaml
└─ requirements.txt


## Як запустити
docker compose up -d --build

## Перевірка логів:
docker compose logs -f app

## Відкрити у браузері:

http://localhost:3000/ — головна

http://localhost:3000/message — форма (поле username, поле message)

Після відправки форми сервер відповість OK, а запис потрапить у MongoDB


## Перегляд даних у MongoDB Compass
mongodb://localhost:27017
DB: webchat → collection: messages