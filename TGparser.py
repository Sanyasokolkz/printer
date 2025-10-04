import re
from typing import Optional, Dict

def find_solana_contract(message: str) -> Optional[Dict[str, object]]:
    """
    Ищет Solana-адрес в сообщении.
    Возвращает словарь с ключами contract/ticker/mcap или None.
    Пока тикер и капу не парсим – ставим None.
    """
    strict_match = re.search(r'^\s*([1-9A-HJ-NP-Za-km-z]{32,44})\s*$', message, re.MULTILINE)
    if strict_match:
        return {"contract": strict_match.group(1).strip(),
                "ticker":   None,
                "mcap":     None}

    pump_match = re.search(r'([1-9A-HJ-NP-Za-km-z]{32,44}pump)', message)
    if pump_match:
        return {"contract": pump_match.group(1),
                "ticker":   None,
                "mcap":     None}

    general_match = re.search(r'([1-9A-HJ-NP-Za-km-z]{32,44})', message)
    if general_match:
        full = general_match.group(0)
        start, end = general_match.start(), general_match.end()
        if (start == 0 or not message[start-1].isalnum()) and \
           (end == len(message) or not message[end].isalnum()):
            return {"contract": full,
                    "ticker":   None,
                    "mcap":     None}
    return None