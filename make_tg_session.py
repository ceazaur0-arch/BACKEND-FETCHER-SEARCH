"""OPTIONAL. Creates the TG_SESSION string for reading public Telegram channels.

Run it once anywhere Python runs (a free Google Colab notebook works from a phone):
    pip install telethon
    python make_tg_session.py
Use a SPARE Telegram account, never your main one. Paste the printed string into the
TG_SESSION environment variable in Render. Keep it secret: it is a login to that account.
Get your api id and hash free at https://my.telegram.org
"""
from telethon.sessions import StringSession
from telethon.sync import TelegramClient

api_id = int(input("api id: ").strip())
api_hash = input("api hash: ").strip()
with TelegramClient(StringSession(), api_id, api_hash) as client:
    print("\nYour TG_SESSION (keep it secret):\n")
    print(client.session.save())
