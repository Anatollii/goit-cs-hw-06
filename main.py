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

# ---------- TCP Socket-сервер (порт 5000, TCP) ----------
def socket_server():  # Функція-процес: піднімає TCP-сервер і пише дані до MongoDB
    mongo = MongoClient(MONGO_URI)  # Створюємо підключення до MongoDB
    coll = mongo[MONGO_DB][MONGO_COL]  # Отримуємо колекцію для запису документів

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:  # Створюємо TCP-сокет (IPv4, потік)
        srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)  # Дозволяємо швидко перевідкрити порт після рестарту
        srv.bind((TCP_HOST, TCP_PORT))  # Прив'язуємо сокет до адреси/порту
        srv.listen(16)  # Починаємо слухати вхідні підключення (черга до 16)
        print(f"[TCP] Listening on {TCP_HOST}:{TCP_PORT}", flush=True)  # Лог у консоль

        while True:  # Нескінченний цикл приймання клієнтів
            conn, addr = srv.accept()  # Приймаємо нове підключення; отримуємо сокет клієнта та його адресу
            try:  # Блок для безпечного читання та обробки
                with conn, conn.makefile("rb") as f:  # Контекст: сокет клієнта + файловий обгортувач для readline()
                    raw = f.readline()  # Читаємо одну строку до '\n' (фреймінг повідомлення)
                    if not raw:  # Якщо клієнт нічого не надіслав — пропускаємо
                        continue
                    try:
                        data = json.loads(raw.decode("utf-8").strip())  # Десеріалізуємо JSON-рядок у dict
                    except json.JSONDecodeError:  # Якщо прийшов некоректний JSON
                        continue  # Ігноруємо таке повідомлення

                    doc = {  # Формуємо документ у потрібному форматі (згідно ТЗ)
                        "date": str(datetime.now()),  # Час отримання повідомлення у вигляді рядка
                        "username": (data.get("username") or "").strip(),  # Ім'я користувача (захист від None)
                        "message": (data.get("message") or "").strip(),  # Текст повідомлення (обрізаємо пробіли)
                    }
                    coll.insert_one(doc)  # Записуємо документ у MongoDB
            except Exception as e:  # Ловимо будь-яку неочікувану помилку на підключенні
                print(f"[TCP] Error {addr}: {e}", file=sys.stderr, flush=True)  # Логуємо у stderr

# ---------- HTTP-сервер (порт 3000) ----------
class App(BaseHTTPRequestHandler):  # Обробник HTTP-запитів (роутинг і віддача файлів/форми)
    def _send(self, code: int, body: bytes, ctype: str):  # Допоміжний метод: відправити відповідь з тілом
        self.send_response(code)  # Статус-код HTTP
        self.send_header("Content-Type", ctype)  # Заголовок типу вмісту
        self.send_header("Content-Length", str(len(body)))  # Довжина тіла відповіді
        self.end_headers()  # Завершення заголовків
        self.wfile.write(body)  # Запис тіла у вихідний потік сокета

    def _file(self, path: Path, ctype: str):  # Віддати файл з диска з вказаним Content-Type
        if path.exists() and path.is_file():  # Перевіряємо, що файл існує
            self._send(200, path.read_bytes(), ctype)  # Відправляємо файл зі статусом 200 OK
        else:
            self._err404()  # Якщо файла немає — 404

    def _err404(self):  # Відповідь 404 Not Found з шаблоном error.html
        err = TPL / "error.html"  # Шлях до файлу помилки
        if err.exists():  # Якщо є шаблон
            self._send(404, err.read_bytes(), "text/html; charset=utf-8")  # Віддати HTML-сторінку 404
        else:
            self._send(404, b"404 Not Found", "text/plain; charset=utf-8")  # Запасний варіант — текст

    # ---- GET ----
    def do_GET(self):  # Обробка HTTP GET-запитів
        p = urlparse(self.path)  # Розбираємо URL
        route = unquote(p.path)  # Отримуємо шлях (декодуємо %xx)

        if route in ("/", "/index", "/index.html"):  # Маршрут головної сторінки
            return self._file(TPL / "index.html", "text/html; charset=utf-8")  # Віддати index.html

        if route in ("/message", "/message.html"):  # Маршрут сторінки з формою
            return self._file(TPL / "message.html", "text/html; charset=utf-8")  # Віддати message.html

        if route == "/static/style.css":  # Маршрут до CSS
            return self._file(ST / "style.css", "text/css; charset=utf-8")  # Віддати style.css

        if route == "/static/logo.png":  # Маршрут до логотипа
            return self._file(ST / "logo.png", "image/png")  # Віддати logo.png

        return self._err404()  # Усі інші шляхи — 404

    # ---- POST ----
    def do_POST(self):  # Обробка HTTP POST-запитів
        p = urlparse(self.path)  # Розбираємо URL
        route = unquote(p.path)  # Отримуємо шлях

        if route == "/message":  # Приймання даних форми з /message
            length = int(self.headers.get("Content-Length", "0"))  # Розмір тіла запиту
            body = self.rfile.read(length).decode("utf-8")  # Читаємо тіло (urlencoded-рядок)
            form = parse_qs(body, keep_blank_values=True)  # Парсимо форму у словник списків

            payload = {  # Готуємо JSON-повідомлення для TCP-сервера
                "username": (form.get("username", [""])[0] or "").strip(),  # Ім'я з форми
                "message": (form.get("message", [""])[0] or "").strip(),  # Текст з форми
            }

            try:
                with socket.create_connection((TCP_SEND_HOST, TCP_PORT), timeout=3) as c:  # Встановлюємо TCP-з'єднання до сокет-сервера
                    c.sendall((json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8"))  # Надсилаємо JSON-рядок + '\n'
            except Exception as e:  # Якщо сокет недоступний
                print(f"[HTTP] TCP send error: {e}", file=sys.stderr, flush=True)

            return self._send(200, b"OK", "text/plain; charset=utf-8")  # Відповідь клієнту за ТЗ — просто "OK"

        return self._err404()  # Інші POST-маршрути — 404

def http_server():  # Процес HTTP-сервера (ThreadingHTTPServer обслуговує запити у потоках)
    httpd = ThreadingHTTPServer((HTTP_HOST, HTTP_PORT), App)  # Створюємо HTTP-сервер
    print(f"[HTTP] Listening on {HTTP_HOST}:{HTTP_PORT}", flush=True)  # Лог про старт
    try:
        httpd.serve_forever()  # Нескінченний цикл обробки запитів
    finally:
        httpd.server_close()  # Закриття сокета сервера при завершенні


if __name__ == "__main__":
    import multiprocessing as mp  # Імпортуємо тут, щоб уникнути проблем з forking на Windows

    mp.set_start_method("spawn", force=True)  # Для Windows встановлюємо старт процесів методом spawn

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

