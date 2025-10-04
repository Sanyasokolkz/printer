import aiohttp
import asyncio
from typing import Optional

class PoolFinder:
    def __init__(self):
        self.session = None
        
    async def init_session(self):
        """Инициализирует постоянную сессию"""
        if self.session is None:
            headers = {
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
                'Accept': 'application/json'
            }
                
            self.session = aiohttp.ClientSession(
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)
            )
            print("🔗 Соединение с DexScreener установлено")

    async def find_pool(self, token_mint: str) -> Optional[str]:
        """Находит лучший пул токена через DexScreener"""
        if self.session is None:
            await self.init_session()
            
        url = f"https://api.dexscreener.com/latest/dex/tokens/{token_mint}"
        
        try:
            async with self.session.get(url) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    pairs = data.get("pairs", [])
                    # Фильтруем только Solana пары
                    solana_pairs = [pair for pair in pairs if pair.get("chainId") == "solana"]
                    
                    if solana_pairs:
                        # Сортируем по ликвидности и берем первый
                        solana_pairs.sort(key=lambda x: float(x.get("liquidity", {}).get("usd", 0)), reverse=True)
                        return solana_pairs[0].get("pairAddress")
                return None
                    
        except Exception as e:
            print(f"❌ DexScreener ошибка: {e}")
            return None

    async def close(self):
        """Закрывает сессию"""
        if self.session:
            await self.session.close()
            print("🔌 Соединение с DexScreener закрыто")

# Глобальный экземпляр
pool_finder = PoolFinder()

async def find_pool_fast(token_address: str) -> Optional[str]:
    """Быстрая функция для поиска пула"""
    return await pool_finder.find_pool(token_address)

async def main():
    """Тест"""
    # Инициализируем сессию
    await pool_finder.init_session()
    
    token_address = "AWgcTbxbMoWWt6tCsHoP6pVbspDn4b6CZBM6qdQ2bonk"
    
    pool = await find_pool_fast(token_address)
    if pool:
        print(f"✅ Пул найден: {pool}")
    else:
        print("❌ Пул не найден")
    
    # Закрываем сессию
    await pool_finder.close()

if __name__ == "__main__":
    asyncio.run(main())