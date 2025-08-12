import json
import socket
import sys
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from pymongo import MongoClient


BASE = Path(__file__).resolve().parent  # папка з main.py
TPL = BASE / "templates"  # щлях до HTML-шаблонів
ST = BASE / "static"  # шлях до CSS та лого

HTTP_HOST = "0.0.0.0"  # слухати всі інтерфейси
HTTP_PORT = 3000

TCP_HOST = "0.0.0.0"  # слухати всі інтерфейси
TCP_PORT = 5000
TCP_SEND_HOST = "127.0.0.1"  # куди HTTP-процес надсилає JSON (локально до TCP-сервера)

MONGO_URI = "mongodb://mongo:27017"
MONGO_DB = "webchat"  # назва БД у MongoDB
MONGO_COL = "messages"  # назва колекції у MongoDB


def socket_server():
    mongo = MongoClient(MONGO_URI)  # створюємо підключення до MongoDB
    coll = mongo[MONGO_DB][MONGO_COL]  # отримуємо колекцію для запису документів

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:  # створюємо TCP-сокет (IPv4, потік)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # швидко перевідкрити порт після рестарту
        srv.bind((TCP_HOST, TCP_PORT))
        srv.listen(16)  # слухаємо, черга до 16
        print(f"[TCP] Listening on {TCP_HOST}:{TCP_PORT}", flush=True)  # Лог у консоль

        while True:
            conn, addr = srv.accept()  # приймаємо нове підключення; отримуємо сокет клієнта та його адресу
            try:
                with conn, conn.makefile("rb") as f:
                    raw = f.readline()
                    if not raw:  # якщо клієнт нічого не надіслав пропускаємо
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8").strip())  # JSON-рядок у dict
                    except json.JSONDecodeError:  # якщо прийшов некоректний JSON
                        continue  # ігноруємо таке повідомлення

                    doc = {  # формуємо документ
                        "date": str(datetime.now()),
                        "username": (data.get("username") or "").strip(),
                        "message": (data.get("message") or "").strip(),
                    }
                    coll.insert_one(doc)  # записуємо документ у MongoDB
            except Exception as e:
                print(f"[TCP] Error {addr}: {e}", file=sys.stderr, flush=True)


class App(BaseHTTPRequestHandler):
    def _send(self, code: int, body: bytes, ctype: str):
        self.send_response(code)  # статус-код HTTP
        self.send_header("Content-Type", ctype)  # заголовок типу вмісту
        self.send_header("Content-Length", str(len(body)))  # довжина тіла відповіді
        self.end_headers()  # завершення
        self.wfile.write(body)  # запис

    def _file(self, path: Path, ctype: str):
        if path.exists() and path.is_file():  # перевіряємо, що файл існує
            self._send(200, path.read_bytes(), ctype)  # відправляємо файл зі статусом 200 OK
        else:
            self._err404()  # якщо файла немає — 404

    def _err404(self):
        err = TPL / "error.html"  # щлях до файлу помилки
        if err.exists():  # якщо є шаблон
            self._send(404, err.read_bytes(), "text/html; charset=utf-8")  # віддати HTML-сторінку 404
        else:
            self._send(404, b"404 Not Found", "text/plain; charset=utf-8")  # запасний варіант


    def do_GET(self):
        p = urlparse(self.path)  # розбираємо URL
        route = unquote(p.path)  # отримуємо шлях

        if route in ("/", "/index", "/index.html"):  # маршрут головної сторінки
            return self._file(TPL / "index.html", "text/html; charset=utf-8")  # віддати index.html

        if route in ("/message", "/message.html"):  # маршрут сторінки з формою
            return self._file(TPL / "message.html", "text/html; charset=utf-8")  # віддати message.html

        if route == "/static/style.css":  # маршрут до CSS
            return self._file(ST / "style.css", "text/css; charset=utf-8")  # віддати style.css

        if route == "/static/logo.png":  # маршрут до логотипа
            return self._file(ST / "logo.png", "image/png")  # віддати logo.png

        return self._err404()  # інші шляхи 404

    # ---- POST ----
    def do_POST(self):
        p = urlparse(self.path)  # розбираємо URL
        route = unquote(p.path)  # отримуємо шлях

        if route == "/message":
            length = int(self.headers.get("Content-Length", "0"))
            body = self.rfile.read(length).decode("utf-8")
            form = parse_qs(body, keep_blank_values=True)

            payload = {  # JSON для TCP-сервера
                "username": (form.get("username", [""])[0] or "").strip(),
                "message": (form.get("message", [""])[0] or "").strip(),
            }

            try:
                with socket.create_connection((TCP_SEND_HOST, TCP_PORT), timeout=3) as c:  # встановлюємо з'єднання
                    c.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))  # надсилаємо JSON
            except Exception as e:  # Якщо сокет недоступний
                print(f"[HTTP] TCP send error: {e}", file=sys.stderr, flush=True)

            return self._send(200, b"OK", "text/plain; charset=utf-8")  # відповідь клієнту "OK"

        return self._err404()  # інші 404

def http_server():  # у потоках
    httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), App)  # Створюємо HTTP-сервер
    print(f"[HTTP] Listening on {HTTP_HOST}:{HTTP_PORT}", flush=True)  # лог про старт
    try:
        httpd.serve_forever()
    finally:
        httpd.server_close()  # закриття сокета сервера при завершенні


if __name__ == "__main__":
    import multiprocessing as mp

    p_tcp = mp.Process(target=socket_server, name="tcp_server")  # Окремий процес для TCP-сервера
    p_http = mp.Process(target=http_server, name="http_server")  # Окремий процес для HTTP-сервера

    p_tcp.start()  # Стартуємо TCP-процес
    p_http.start()  # Стартуємо HTTP-процес

    try:
        p_tcp.join()  # Чекаємо завершення TCP-процесу
        p_http.join()  # Чекаємо завершення HTTP-процесу
    except KeyboardInterrupt:  # Коректне завершення по Ctrl+C
        for p in (p_http, p_tcp):  # Проходимо по процесах
            if p.is_alive():  # Якщо процес ще працює
                p.terminate()  # Відправляємо сигнал на зупинку
        for p in (p_http, p_tcp):  # Друга фаза — дочекатися зупинки
            p.join()  # Очікуємо поки процес завершиться

