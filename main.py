#!/usr/bin/env python3
import asyncio
import os
import time
from telethon import TelegramClient, events
from telethon.sessions import StringSession
from trading.wizard_trader import WizardTrader
from TGparser import find_solana_contract
from TokenMonitor import token_monitor
from config import *

# --------------- клиент Telegram ---------------
session_str = os.getenv("SESSION_BASE64")
if not session_str:
    print("❌ SESSION_BASE64 не найден в переменных окружения")
    exit(1)

session_bytes = __import__("base64").b64decode(session_str.encode())
client = TelegramClient(StringSession(session_bytes.decode()), api_id, api_hash)

# --------------- трейдер ---------------
if APP != "Wizard":
    raise ValueError(f"Неизвестный APP: {APP}")
trader = WizardTrader(wizard_chat_id)

# --------------- обработчик новых постов ---------------
@client.on(events.NewMessage(chats=[channel_username]))
async def handler(event):
    call_time = time.time()
    data = find_solana_contract(event.raw_text)
    if not data:
        return

    if max_mcap and data.get("mcap", 0) > max_mcap:
        print(f"❌ Макеткап {data['mcap']} выше лимита")
        return

    print(f"📢 Новое сообщение: [{data.get('ticker') or '???'}] {data['contract']}")
    ok = await trader.trade_token(data["contract"],
                                  data.get("ticker"),
                                  call_time,
                                  data.get("mcap"),
                                  client)
    print("✅ Сделка завершена" if ok else "❌ Ошибка торговли")

# --------------- запуск ---------------
async def main():
    await token_monitor.start_monitoring()
    await client.start()
    print("🚀 Бот запущен")
    await client.run_until_disconnected()

if __name__ == "__main__":
    asyncio.run(main())