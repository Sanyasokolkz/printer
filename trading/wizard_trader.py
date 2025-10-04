import asyncio
import aiohttp
import time
import requests
from utils.PoolFinder import find_pool_fast
from utils.onchain import get_sol_price, get_token_supply
from TokenMonitor import token_monitor
from database.trade_logger import trade_logger

class WizardTrader:
    def __init__(self, chat_id: str):
        """
        Инициализация WizardTrader
        chat_id: ID чата куда отправлять контракты токенов
        """
        self.chat_id = chat_id
        self.monitor_task = None
        self.current_token = None

    async def send_token_to_chat(self, token_address: str, client):
        """
        Отправляет контракт токена в указанный чат
        """
        try:
            # Пробуем отправить сообщение
            await client.send_message(self.chat_id, token_address)
            print(f"📤 Отправлен контракт {token_address[:8]}... в чат {self.chat_id}")
        except Exception as e:
            print(f"❌ Ошибка отправки в чат: {e}")

    async def trade_token(self, token_address, ticker=None, call_start_time=None, call_cap=None, client=None):
        """Асинхронная основная функция торговли"""

        total_start = time.time()
        step_times = {}

        # Сначала отправляем контракт в чат
        send_start = time.time()
        await self.send_token_to_chat(token_address, client)
        step_times['send_to_chat'] = (time.time() - send_start) * 1000

        # Параллельные запросы - измеряем время каждого отдельно
        async with aiohttp.ClientSession() as session:
            # Функции с измерением времени
            async def timed_sol():
                start = time.time()
                result = await get_sol_price(session)
                return result, (time.time() - start) * 1000
                
            async def timed_supply():
                start = time.time()
                result = await get_token_supply(token_address)
                return result, (time.time() - start) * 1000
            
            # Запускаем задачи параллельно
            sol_task = asyncio.create_task(timed_sol())
            supply_task = asyncio.create_task(timed_supply())
            
            # Ждем задачи параллельно
            (sol_price, sol_time), (token_supply, supply_time) = await asyncio.gather(sol_task, supply_task)
            
        step_times['sol'] = sol_time
        step_times['supply'] = supply_time
        step_times['parallel_requests'] = max(sol_time, supply_time)  # Максимальное время

        # Добавляем токен в мониторинг с предварительными данными
        token_monitor.add_token(token_address)
        token_monitor.active_tokens[token_address]['ticker'] = ticker
        
        # Ждем только сигнатуру покупки (для точного измерения времени)
        buy_monitor_start = time.time()
        buy_signature = await token_monitor.wait_for_buy_signature_only(token_address, timeout=120.0)
        
        if buy_signature:
            print(f"\n✅ Сигнатура покупки найдена!")
            
            # Теперь получаем полные детали транзакции
            buy_info = await token_monitor.wait_for_buy(token_address, timeout=30.0)
            
            if not buy_info:
                print(f"❌ Не удалось получить детали транзакции для {token_address[:8]}...")
                token_monitor.remove_token(token_address)
                return False
                
            # Обрабатываем покупку
            token_amount = buy_info.get('token_amount', 0.0)
            sol_pure = buy_info.get('sol_spent_pure')
            
            print(f"✅ BUY транзакция найдена!")
            print(f"   🪙 Token: {token_address[:8]}...")
            print(f"   📦 Amount: {token_amount:.6f}")
            print(f"   🔻 Потрачено (по кошельку): {buy_info.get('sol_spent_wallet', 0.0):.9f} SOL")
            if sol_pure is not None:
                print(f"   💎 Потрачено (чисто своп):   {sol_pure:.9f} SOL")
                
                # Расчет цены
                if token_amount > 0:
                    buy_price = sol_pure / token_amount
                    price_in = buy_price * sol_price
                    mcap = price_in * token_supply
                    
                    # Форматируем цену без научной нотации
                    if price_in < 0.000001:
                        price_str = f"{price_in:.12f}"
                    elif price_in < 0.001:
                        price_str = f"{price_in:.9f}"
                    elif price_in < 1:
                        price_str = f"{price_in:.6f}"
                    else:
                        price_str = f"{price_in:.3f}"
                    
                    # Используем время из token_monitor
                    signature_time = token_monitor.get_signature_time(buy_signature)
                    if signature_time and call_start_time:
                        signature_detection_time = (signature_time - call_start_time) * 1000
                        print(f'💰 Цена покупки: {price_str} USD | Капа: {mcap:,.0f} | время ({signature_detection_time:.0f}ms) | Токен: {token_address[:8]}...')
                    else:
                        print(f'💰 Цена покупки: {price_str} USD | Капа: {mcap:,.0f} | Токен: {token_address[:8]}...')
                    
                    # Сохраняем данные для token_monitor
                    token_monitor.active_tokens[token_address]['entry_mcap'] = mcap
                    token_monitor.active_tokens[token_address]['ticker'] = ticker
                    token_monitor.active_tokens[token_address]['remaining_position'] = token_amount
                    token_monitor.active_tokens[token_address]['sell_transactions'] = []
                    
                    # Логируем покупку в JSON после расчета всех данных
                    if 'buy_signature' in token_monitor.active_tokens[token_address]:
                        trade_logger.add_buy(token_address, ticker, mcap, token_monitor.active_tokens[token_address]['buy_signature'], call_cap, token_amount, signature_time)
                        print(f"📝 Покупка записана в JSON для токена {token_address[:8]}...")
        else:
            print(f"❌ Покупка не найдена для токена {token_address[:8]}... (timeout)")
            # Удаляем токен из мониторинга если покупка не найдена
            token_monitor.remove_token(token_address)
            return False
        
        # Добавляем задержку между покупкой и продажей
        await asyncio.sleep(1)
        
        # Ждем все продажи до полной продажи позиции (таймаут 6 часов)
        sell_start = time.time()
        entry_mcap = token_monitor.active_tokens[token_address]['entry_mcap']
        sell_transactions = await token_monitor.wait_for_all_sells(token_address, timeout=21600.0)
        sell_detection_time = (time.time() - sell_start) * 1000
        
        if sell_transactions:
            print(f"\n✅ Найдено продаж: {len(sell_transactions)}")
            
            # Обрабатываем каждую продажу
            total_sold_amount = 0
            total_sol_received = 0
            
            for i, sell_tx in enumerate(sell_transactions, 1):
                sell_info = sell_tx['info']
                token_amount = sell_info.get('token_amount', 0.0)
                sol_pure = sell_info.get('sol_received_pure')
                
                print(f"\n   📦 Продажа #{i}:")
                print(f"   🪙 Token: {token_address[:8]}...")
                print(f"   📦 Amount: {token_amount:.6f}")
                print(f"   🔺 Получено (по кошельку):  {sell_info.get('sol_received_wallet', 0.0):.9f} SOL")
                if sol_pure is not None:
                    print(f"   💎 Получено (чисто своп):   {sol_pure:.9f} SOL")
                    
                    # Расчет цены для этой продажи
                    if token_amount > 0:
                        sell_price = sol_pure / token_amount
                        price_in = sell_price * sol_price
                        mcap = price_in * token_supply
                        
                        # Форматируем цену без научной нотации
                        if price_in < 0.000001:
                            price_str = f"{price_in:.12f}"
                        elif price_in < 0.001:
                            price_str = f"{price_in:.9f}"
                        elif price_in < 1:
                            price_str = f"{price_in:.6f}"
                        else:
                            price_str = f"{price_in:.3f}"
                        
                        print(f'   💰 Цена продажи #{i}: {price_str} USD | Капа: {mcap:,.0f}')
                        
                        # Логируем продажу в JSON
                        sell_signature = sell_tx.get('signature', '')
                        if sell_signature:
                            # Рассчитываем процент используя сохраненный entry_mcap
                            sell_percent = ((mcap - entry_mcap) / entry_mcap) * 100 if entry_mcap > 0 else 0
                            
                            trade_logger.add_sell(token_address, sell_signature, mcap, sell_percent, token_amount)
                            print(f"   📝 Продажа #{i} записана в JSON | Percent: {sell_percent:.1f}%")
                        
                        total_sold_amount += token_amount
                        total_sol_received += sol_pure
            
            # Итоговая статистика по всем продажам
            if sell_transactions and total_sold_amount > 0:
                avg_sell_price = total_sol_received / total_sold_amount
                avg_price_in = avg_sell_price * sol_price
                avg_mcap = avg_price_in * token_supply
                
                print(f"\n📊 Итоговая статистика:")
                print(f"   💰 Средняя цена продажи: {avg_price_in:.6f} USD")
                print(f"   📈 Средняя капа продажи: {avg_mcap:,.0f}")
                print(f"   📦 Всего продано: {total_sold_amount:.6f} токенов")
                print(f"   💎 Всего получено: {total_sol_received:.9f} SOL")
        else:
            print(f"❌ Продажи не найдены для токена {token_address[:8]}...")
        
        # Финализируем сделку и рассчитываем итоговый PnL
        if sell_transactions:
            trade_logger.finalize_trade(token_address)
            print(f"📊 Сделка завершена для токена {token_address[:8]}...")
        
        # Токен уже удален из мониторинга в token_monitor при полной продаже

        return True
