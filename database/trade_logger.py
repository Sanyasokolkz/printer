import json
import os
import time
from datetime import datetime
from typing import Dict, Optional, List

class TradeLogger:
    def __init__(self, file_path: str = "trades.json"):
        self.file_path = file_path
        self.trades = self._load_trades()
        # Создаем пустой файл если его нет
        if not os.path.exists(self.file_path):
            self._save_trades()
        
    def _load_trades(self) -> Dict:
        """Загружает существующие сделки из JSON файла"""
        if os.path.exists(self.file_path):
            try:
                with open(self.file_path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, FileNotFoundError):
                return {}
        return {}
        
    def _save_trades(self):
        """Сохраняет сделки в JSON файл"""
        with open(self.file_path, 'w', encoding='utf-8') as f:
            json.dump(self.trades, f, indent=2, ensure_ascii=False)
            
    def add_buy(self, token_address: str, ticker: str, entry_cap: float, buy_signature: str, call_cap: float = None, tokens: float = None, signature_time: float = None):
        """Добавляет информацию о покупке"""
        if token_address not in self.trades:
            # Конвертируем время в миллисекунды если оно передано
            signature_time_ms = signature_time * 1000 if signature_time else None
            
            self.trades[token_address] = {
                "ticker": ticker,
                "call_cap": call_cap,
                "entry_cap": entry_cap,
                "tokens": tokens,
                "sell_cap": [],
                "sell_percent": [],
                "tokens_for_sale": [],
                "buy_transaction": f"https://solscan.io/tx/{buy_signature}",
                "sell_transactions": [],
                "total_pnl": 0.0,
                "entry_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "exit_time": None,
                "signature_time": signature_time_ms
            }
            self._save_trades()
            
    def add_sell(self, token_address: str, sell_signature: str, sell_cap: float, sell_percent: float, tokens_for_sale: float = None):
        """Добавляет информацию о продаже"""
        if token_address in self.trades:
            # Проверяем и создаем поля если их нет (для совместимости со старыми версиями)
            if "tokens_for_sale" not in self.trades[token_address]:
                self.trades[token_address]["tokens_for_sale"] = []
            if "tokens" not in self.trades[token_address]:
                self.trades[token_address]["tokens"] = 0
                
            # Проверяем дубликаты - не добавляем если сигнатура уже есть
            sell_transaction_url = f"https://solscan.io/tx/{sell_signature}"
            if sell_transaction_url in self.trades[token_address]["sell_transactions"]:
                print(f"⚠️ Продажа {sell_signature[:8]}... уже записана для токена {token_address[:8]}...")
                return
                
            self.trades[token_address]["sell_transactions"].append(sell_transaction_url)
            self.trades[token_address]["sell_cap"].append(sell_cap)
            self.trades[token_address]["sell_percent"].append(sell_percent)
            self.trades[token_address]["tokens_for_sale"].append(tokens_for_sale)
            self._save_trades()
            
    def finalize_trade(self, token_address: str, total_pnl: float = None):
        """Завершает сделку и рассчитывает итоговый PnL"""
        if token_address in self.trades:
            if total_pnl is None:
                # Рассчитываем PnL автоматически
                total_pnl = self._calculate_total_pnl(token_address)
            
            self.trades[token_address]["total_pnl"] = total_pnl
            self.trades[token_address]["exit_time"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._save_trades()
            
    def _calculate_total_pnl(self, token_address: str) -> float:
        """Рассчитывает итоговый PnL по формуле: (токены_которые_продали / tokens * пнл_продажи_%) + ..."""
        trade_data = self.trades[token_address]
        total_tokens = trade_data.get("tokens", 0)
        tokens_for_sale = trade_data.get("tokens_for_sale", [])
        sell_percent = trade_data.get("sell_percent", [])
        
        if total_tokens <= 0:
            return 0.0
            
        total_pnl = 0.0
        for i, tokens_sold in enumerate(tokens_for_sale):
            if i < len(sell_percent):
                # PnL = (токены_которые_продали / tokens * пнл_продажи_%)
                pnl_contribution = (tokens_sold / total_tokens) * sell_percent[i]
                total_pnl += pnl_contribution
                
        return total_pnl
            
    def get_trade_summary(self, token_address: str) -> Optional[Dict]:
        """Получает сводку по сделке"""
        return self.trades.get(token_address)
        
    def get_all_trades(self) -> Dict:
        """Получает все сделки"""
        return self.trades
        
    def get_trades_by_date(self, date: str) -> Dict:
        """Получает сделки за определенную дату"""
        filtered_trades = {}
        for token_address, trade_data in self.trades.items():
            if trade_data.get("entry_time", "").startswith(date):
                filtered_trades[token_address] = trade_data
        return filtered_trades

# Глобальный экземпляр логгера
trade_logger = TradeLogger() 