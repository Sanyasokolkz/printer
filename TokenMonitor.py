import asyncio
import aiohttp
import json
import websockets
import threading
import time
from typing import Dict, Optional
from config import RPC_URL, WEBSOCKET_URL, wallet_address

# Импортируем trade_logger
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))
from database.trade_logger import trade_logger

class TokenMonitor:
    def __init__(self):
        self.active_tokens: Dict[str, Dict] = {}  # token_address -> {buy_signature, buy_info, remaining_position, sell_transactions}
        self.processed_signatures = set()
        self.cache_lock = threading.Lock()
        self.websocket = None
        self.monitoring = False
        self.signature_timestamps = {}  # Кэш времени нахождения сигнатур
        self.wallet_address = None  # Будет установлен из main_test.py
        
        # Callback'и для уведомления о событиях
        self.on_buy_detected = None
        self.on_sell_detected = None
        
    async def start_monitoring(self):
        """Запускает глобальный мониторинг всех транзакций"""
        if self.monitoring:
            return
            
        self.monitoring = True
        asyncio.create_task(self._monitor_websocket())
        
    async def stop_monitoring(self):
        """Останавливает мониторинг"""
        self.monitoring = False
        if self.websocket:
            await self.websocket.close()
            
    async def _monitor_websocket(self):
        """Глобальный мониторинг WebSocket"""
        while self.monitoring:
            try:
                async with websockets.connect(WEBSOCKET_URL) as ws:
                    self.websocket = ws
                    
                    # Используем wallet_address из main_test.py, если установлен
                    target_wallet = self.wallet_address if self.wallet_address else wallet_address
                    
                    sub_msg = {
                        "jsonrpc": "2.0",
                        "id": 1,
                        "method": "logsSubscribe",
                        "params": [
                            {"mentions": [target_wallet]},
                            {"commitment": "confirmed"}
                        ]
                    }
                    await ws.send(json.dumps(sub_msg))
                    await ws.recv()  # confirm
                    
                    print(f"📡 Глобальный мониторинг запущен для: {target_wallet}")
                    
                    while self.monitoring:
                        msg = await ws.recv()
                        data = json.loads(msg)
                        
                        if data.get("method") != "logsNotification":
                            continue
                            
                        tx_value = data.get("params", {}).get("result", {}).get("value", {})
                        if not tx_value or tx_value.get("err"):
                            continue
                            
                        signature = tx_value["signature"]
                        
                        # СТОП! Сохраняем время сразу при получении сигнатуры
                        self.signature_timestamps[signature] = time.time()
                        
                        await self._process_transaction(signature)
                        
            except Exception as e:
                print(f"🔴 Ошибка WebSocket: {e}, переподключение через 5 секунд...")
                await asyncio.sleep(5)
                
    async def _process_transaction(self, signature: str):
        """Обрабатывает транзакцию и определяет, к какому токену она относится"""
        # Проверяем кэш
        with self.cache_lock:
            if signature in self.processed_signatures:
                return
            self.processed_signatures.add(signature)
        
        print(f"🔍 Обрабатываем транзакцию: {signature[:8]}...")
        
        # Получаем детали транзакции
        tx_info = await self._get_transaction_details(signature)
        if not tx_info:
            print(f"❌ Не удалось получить детали транзакции: {signature[:8]}...")
            return
            
        token_address = tx_info.get('token_address')
        direction = tx_info.get('direction')
        
        print(f"🔍 Транзакция {signature[:8]}... | Токен: {token_address[:8] if token_address else 'N/A'} | Направление: {direction}")
        print(f"🔍 Отслеживаемые токены: {list(self.active_tokens.keys())}")
        
        # Проверяем, отслеживается ли этот токен
        if token_address not in self.active_tokens:
            print(f"❌ Токен {token_address[:8] if token_address else 'N/A'} не отслеживается")
            return
            
        token_data = self.active_tokens[token_address]
        
        if direction == 'buy' and 'buy_signature' not in token_data:
            # Это покупка для отслеживаемого токена
            token_amount = tx_info.get('token_amount', 0.0)
            token_data['buy_signature'] = signature
            token_data['buy_info'] = tx_info
            token_data['remaining_position'] = token_amount
            token_data['sell_transactions'] = []
            
            print(f"✅ Покупка найдена для токена {token_address[:8]}... | Количество: {token_amount:.6f}")
            
            # Вызываем callback если установлен
            if self.on_buy_detected:
                try:
                    await self.on_buy_detected(signature, token_address)
                except Exception as e:
                    print(f"❌ Ошибка в callback покупки: {e}")

            
        elif direction == 'sell':
            # Это продажа для отслеживаемого токена
            token_amount = tx_info.get('token_amount', 0.0)
            
            # Проверяем, что покупка уже была найдена
            if 'remaining_position' not in token_data:
                print(f"🔍 Продажа {signature[:8]}... для {token_address[:8]}... но remaining_position не найден. Токен: {list(token_data.keys())}")
                return
                
            # Добавляем продажу в список транзакций
            sell_tx = {
                'signature': signature,
                'info': tx_info,
                'amount': token_amount
            }
            token_data['sell_transactions'].append(sell_tx)
            
            # Уменьшаем оставшуюся позицию
            token_data['remaining_position'] -= token_amount
            
            # Получаем данные о цене и капе для лога
            sell_price_info = await self._get_sell_price_info(tx_info, token_data)
            if sell_price_info:
                sell_mcap = sell_price_info.get('mcap', 0)
                entry_mcap = sell_price_info.get('entry_mcap', 0)
                mcap_change_percent = sell_price_info.get('mcap_change_percent', 0)
                
                # Логирование продаж перенесено в Wizard_trader.py для избежания дублирования
                
                print(f"✅ Продажа найдена для токена {token_address[:8]}... | Продано: {token_amount:.6f} | Осталось: {token_data['remaining_position']:.6f} | Капа: {sell_mcap:,.0f} ({mcap_change_percent:+.1f}%)")
            else:
                print(f"✅ Продажа найдена для токена {token_address[:8]}... | Продано: {token_amount:.6f} | Осталось: {token_data['remaining_position']:.6f}")
            
            # Вызываем callback если установлен
            if self.on_sell_detected:
                try:
                    await self.on_sell_detected(signature, token_address)
                except Exception as e:
                    print(f"❌ Ошибка в callback продажи: {e}")
            
            # Если позиция полностью продана, удаляем токен из мониторинга
            if token_data['remaining_position'] <= 0:
                print(f"🎯 Позиция полностью продана для токена {token_address[:8]}... | Всего продаж: {len(token_data['sell_transactions'])}")
                
                # Финализация сделки перенесена в Wizard_trader.py для избежания дублирования

            
    async def _get_transaction_details(self, signature: str, retries: int = 15, delay: float = 1.0):
        """Получает детали транзакции"""
        for attempt in range(retries):
            async with aiohttp.ClientSession() as session:
                payload = {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "getTransaction",
                    "params": [
                        signature,
                        {"encoding": "jsonParsed", "maxSupportedTransactionVersion": 0}
                    ]
                }
                
                try:
                    async with session.post(RPC_URL, json=payload, timeout=10) as resp:
                        if resp.status != 200:
                            await asyncio.sleep(delay)
                            continue
                            
                        data = await resp.json()
                        result = data.get("result")
                        if not result:
                            await asyncio.sleep(delay)
                            continue
                            
                        meta = result.get("meta")
                        if not meta or meta.get("err"):
                            return None
                            
                        try:
                            keys = result["transaction"]["message"]["accountKeys"]
                            accounts = [a["pubkey"] for a in keys]
                            
                            # Используем wallet_address из main_test.py, если установлен
                            target_wallet = self.wallet_address if self.wallet_address else wallet_address
                            
                            if target_wallet not in accounts:
                                return None
                                
                            idx = accounts.index(target_wallet)
                            sol_change = (meta["postBalances"][idx] - meta["preBalances"][idx]) / 1e9
                        except (KeyError, ValueError, IndexError) as e:
                            return None
                            
                        pre_tokens = {
                            b["mint"]: float(b["uiTokenAmount"].get("uiAmountString", "0.0"))
                            for b in meta.get("preTokenBalances", [])
                            if b.get("owner") == target_wallet
                        }
                        
                        for post in meta.get("postTokenBalances", []):
                            if post.get("owner") != target_wallet:
                                continue
                                
                            mint = post["mint"]
                            post_amt = float(post["uiTokenAmount"].get("uiAmountString", "0.0"))
                            pre_amt = pre_tokens.get(mint, 0.0)
                            delta = post_amt - pre_amt
                            
                            if delta > 0 and sol_change < 0:  # Покупка
                                pure_sol_swap = self._extract_pure_sol_swap(meta, "buy")
                                return {
                                    "direction": "buy",
                                    "signature": signature,
                                    "token_address": mint,
                                    "token_amount": delta,
                                    "sol_spent_wallet": abs(sol_change),
                                    "sol_spent_pure": pure_sol_swap
                                }
                                
                            if delta < 0:  # Продажа
                                # Используем логику из test.py для парсинга продаж
                                swap_details = self._parse_swap_transaction(result, wallet_address)
                                sol_received = 0.0
                                
                                # Ищем SOL в полученных токенах
                                for received in swap_details.get("received", []):
                                    if received["mint"] == "So11111111111111111111111111111111111111112":
                                        sol_received = received["amount_received"]
                                        break
                                
                                return {
                                    "direction": "sell",
                                    "signature": signature,
                                    "token_address": mint,
                                    "token_amount": abs(delta),
                                    "sol_received_wallet": sol_change,
                                    "sol_received_pure": sol_received
                                }
                        
                        return None
                        
                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    await asyncio.sleep(delay)
                    
        return None
        
    def _parse_swap_transaction(self, result, user_wallet_address: str) -> dict:
        """
        Парсит транзакцию свапа и возвращает, какие токены были отправлены
        и получены пользователем (логика из test.py).
        """
        try:
            meta = result.get('meta')
            if not meta:
                return {"sent": [], "received": []}

            pre_balances = meta.get('preTokenBalances', [])
            post_balances = meta.get('postTokenBalances', [])

            # Создаем карту балансов ДО для всех счетов
            pre_balances_map = {
                item['accountIndex']: {
                    'mint': item['mint'],
                    'owner': item.get('owner'),
                    'amount': float(item['uiTokenAmount']['uiAmountString'])
                }
                for item in pre_balances if item.get('uiTokenAmount', {}).get('uiAmountString')
            }

            sent_tokens = []
            received_tokens = []

            # Проходим по балансам ПОСЛЕ
            for post_bal in post_balances:
                account_index = post_bal.get('accountIndex')
                owner = post_bal.get('owner')
                post_amount_str = post_bal.get('uiTokenAmount', {}).get('uiAmountString')
                
                if not post_amount_str or account_index not in pre_balances_map:
                    continue

                pre_bal_info = pre_balances_map[account_index]
                pre_amount = pre_bal_info['amount']
                post_amount = float(post_amount_str)
                amount_change = post_amount - pre_amount

                # Ищем только значительные изменения
                if abs(amount_change) > 1e-9:
                    # Если баланс УМЕНЬШИЛСЯ
                    if amount_change < 0:
                        # Если это кошелек пользователя - значит, он ОТДАЛ токены
                        if owner == user_wallet_address:
                            amount_sent = abs(amount_change)
                            sent_tokens.append({
                                "mint": post_bal['mint'],
                                "amount_sent": amount_sent
                            })
                        # Если это НЕ кошелек пользователя - значит, он ПОЛУЧИЛ токены от DEX
                        else:
                            amount_received = abs(amount_change)
                            received_tokens.append({
                                "mint": post_bal['mint'],
                                "amount_received": amount_received
                            })
            
            return {"sent": sent_tokens, "received": received_tokens}

        except Exception as e:
            return {"sent": [], "received": []}
        
    def _extract_pure_sol_swap(self, meta, direction: str):
        """
        Извлекает "чистую" сумму SOL из свапа, анализируя внутренние инструкции.
        - Для 'buy': ищет перевод SOL, где наш кошелек является 'authority'.
        - Для 'sell': ищет временные wSOL аккаунты, принадлежащие нам, и находит перевод на них.
        """
        try:
            wsol_mint = "So11111111111111111111111111111111111111112"
            inner_instructions = meta.get("innerInstructions", [])
            
            # Используем wallet_address из main_test.py, если установлен
            target_wallet = self.wallet_address if self.wallet_address else wallet_address

            if direction == "buy":
                for ix in inner_instructions:
                    for inst in ix.get("instructions", []):
                        parsed = inst.get("parsed", {})
                        if inst.get("program") == "spl-token" and parsed.get("type") == "transferChecked":
                            info = parsed.get("info", {})
                            if info.get("mint") == wsol_mint and info.get("authority") == target_wallet:
                                return float(info.get("tokenAmount", {}).get("uiAmount", 0.0))

            elif direction == "sell":
                # Шаг 1: Найти все временные wSOL-аккаунты, принадлежащие нашему кошельку.
                owned_temp_wsol_accounts = set()
                for ix in inner_instructions:
                    for inst in ix.get("instructions", []):
                        parsed = inst.get("parsed", {})
                        if parsed.get("type") in ["initializeAccount", "initializeAccount3"]:
                            info = parsed.get("info", {})
                            if info.get("owner") == target_wallet and info.get("mint") == wsol_mint:
                                owned_temp_wsol_accounts.add(info.get("account"))

                # Шаг 2: Найти перевод wSOL на один из этих временных аккаунтов.
                if owned_temp_wsol_accounts:
                    for ix in inner_instructions:
                        for inst in ix.get("instructions", []):
                            parsed = inst.get("parsed", {})
                            if inst.get("program") == "spl-token" and parsed.get("type") == "transferChecked":
                                info = parsed.get("info", {})
                                if info.get("mint") == wsol_mint and info.get("destination") in owned_temp_wsol_accounts:
                                    return float(info.get("tokenAmount", {}).get("uiAmount", 0.0))

        except Exception as e:
            pass
        return None
        
    async def _get_sell_price_info(self, sell_tx_info: dict, token_data: dict) -> Optional[dict]:
        """Получает информацию о цене и капе для продажи"""
        try:
            from utils.onchain import get_sol_price, get_token_supply
            
            # Получаем данные о продаже
            token_amount = sell_tx_info.get('token_amount', 0.0)
            sol_pure = sell_tx_info.get('sol_received_pure')
            
            if not sol_pure or token_amount <= 0:
                return None
                
            # Получаем цену SOL и supply токена
            async with aiohttp.ClientSession() as session:
                sol_price = await get_sol_price(session)
                token_supply = await get_token_supply(sell_tx_info.get('token_address'))
                
                if not sol_price or not token_supply:
                    return None
                    
                # Рассчитываем цену и капу продажи
                sell_price = sol_pure / token_amount
                price_in = sell_price * sol_price
                sell_mcap = price_in * token_supply
                
                # Получаем капу входа из WL_trader (если доступна)
                entry_mcap = token_data.get('entry_mcap', 0)
                
                # Рассчитываем изменение капы
                if entry_mcap and entry_mcap > 0:
                    mcap_change_percent = ((sell_mcap - entry_mcap) / entry_mcap) * 100
                else:
                    mcap_change_percent = 0
                    
                return {
                    'mcap': sell_mcap,
                    'entry_mcap': entry_mcap,
                    'mcap_change_percent': mcap_change_percent
                }
                
        except Exception as e:
            return None
        
    def add_token(self, token_address: str):
        """Добавляет токен для отслеживания"""
        self.active_tokens[token_address] = {}
        print(f"📝 Добавлен токен для отслеживания: {token_address[:8]}... (всего: {len(self.active_tokens)})")
        
    def remove_token(self, token_address: str):
        """Удаляет токен из отслеживания"""
        if token_address in self.active_tokens:
            del self.active_tokens[token_address]
            
    async def wait_for_buy_signature_only(self, token_address: str, timeout: float = 60.0) -> Optional[str]:
        """Ждет только сигнатуру покупки (без деталей транзакции)"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if token_address in self.active_tokens:
                token_data = self.active_tokens[token_address]
                if 'buy_signature' in token_data:
                    return token_data['buy_signature']
            await asyncio.sleep(0.1)
        return None
        
    async def wait_for_buy(self, token_address: str, timeout: float = 60.0) -> Optional[dict]:
        """Ждет покупку для конкретного токена"""
        start_time = time.time()
        while time.time() - start_time < timeout:
            if token_address in self.active_tokens:
                token_data = self.active_tokens[token_address]
                if 'buy_signature' in token_data:
                    return token_data['buy_info']
            await asyncio.sleep(0.1)
        return None
        
    def get_signature_time(self, signature: str) -> Optional[float]:
        """Возвращает время нахождения сигнатуры"""
        return self.signature_timestamps.get(signature)
        
    async def wait_for_all_sells(self, token_address: str, timeout: float = 21600.0) -> list:
        """Ждет все продажи для конкретного токена до полной продажи позиции"""
        start_time = time.time()
        print(f"🔍 Начинаем ожидание продаж для токена {token_address[:8]}...")
        
        while time.time() - start_time < timeout:
            if token_address in self.active_tokens:
                token_data = self.active_tokens[token_address]
                
                # Проверяем, полностью ли продана позиция
                if token_data.get('remaining_position', 0) <= 0:
                    sell_transactions = token_data.get('sell_transactions', [])
                    print(f"✅ Позиция завершена для токена {token_address[:8]}... | Продаж: {len(sell_transactions)} | remaining_position: {token_data.get('remaining_position', 0)}")
                    # Удаляем токен из мониторинга после возврата транзакций
                    self.remove_token(token_address)
                    return sell_transactions
                    
            else:
                # Токен больше не отслеживается - позиция полностью продана
                print(f"❌ Токен {token_address[:8]}... больше не отслеживается")
                return []
                
            await asyncio.sleep(0.1)
        
        print(f"⏰ Таймаут ожидания продаж для токена {token_address[:8]}...")
        return []
    
    async def wait_for_buy_transaction(self, token_address: str, timeout: float = 60.0) -> Optional[dict]:
        """Ждет покупку для конкретного токена и возвращает детали транзакции"""
        start_time = time.time()
        print(f"🔍 Начинаем ожидание покупки для токена {token_address[:8]}...")
        
        while time.time() - start_time < timeout:
            if token_address in self.active_tokens:
                token_data = self.active_tokens[token_address]
                
                # Проверяем, найдена ли покупка
                if 'buy_signature' in token_data:
                    buy_info = token_data.get('buy_info', {})
                    buy_signature = token_data.get('buy_signature', '')
                    token_amount = token_data.get('remaining_position', 0)
                    
                    print(f"✅ Покупка найдена для токена {token_address[:8]}... | Сигнатура: {buy_signature[:8]}... | Количество: {token_amount:.6f}")
                    
                    # Возвращаем детали покупки
                    return {
                        'signature': buy_signature,
                        'token_address': token_address,
                        'token_amount': token_amount,
                        'buy_info': buy_info,
                        'timestamp': self.get_signature_time(buy_signature)
                    }
                    
            else:
                # Токен больше не отслеживается
                print(f"❌ Токен {token_address[:8]}... больше не отслеживается")
                return None
                
            await asyncio.sleep(0.1)
        
        print(f"⏰ Таймаут ожидания покупки для токена {token_address[:8]}...")
        return None

# Глобальный экземпляр монитора
token_monitor = TokenMonitor() 