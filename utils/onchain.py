import asyncio
import aiohttp
import re
import sys
import os
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from solana.rpc.async_api import AsyncClient
from solders.pubkey import Pubkey
from config import *

solana_client = AsyncClient(RPC_URL)


async def get_token_supply(token_address: str) -> float | None:
    try:
        pubkey = Pubkey.from_string(token_address)
        response = await solana_client.get_token_supply(pubkey)
        if response.value:
            amount = int(response.value.amount)
            decimals = int(response.value.decimals)
            supply = amount / (10 ** decimals)
            return supply
        else:
            print("[LOG] Пустой ответ от RPC при получении total supply")
    except Exception as e:
        print(f"[LOG] Ошибка при получении total supply: {e}")
    return None


async def get_sol_price(session):
    url = "https://api.binance.com/api/v3/ticker/price?symbol=SOLUSDT"
    async with session.get(url, timeout=1) as resp:
        data = await resp.json()
        return float(data["price"])