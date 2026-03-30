"""
Telegram Natural Language Query Interface (P4)
src/interfaces/telegram_bot.py
"""
import os
import time
import json
import logging
import threading
import requests
from src.agents.llm_provider import LLMProvider
from config.settings import settings

logger = logging.getLogger("TelegramBot")

class TelegramQueryBot:
    def __init__(self, token: str, chat_id: str):
        self.token = token
        self.chat_id = str(chat_id)
        self.api_url = f"https://api.telegram.org/bot{token}"
        self.last_update_id = 0
        
        # Instantiate LLM provider directly
        self.llm = LLMProvider.create()
        self.running = False
        
    def _get_system_state(self) -> str:
        try:
            with open("logs/status.json", "r") as f:
                state = json.load(f)
            
            # Compress state significantly to fit LLM token context windows
            lite_state = {
                "regime": state.get("regime"),
                "pnl": state.get("pnl"),
                "positions": state.get("positions"),
                "signals": state.get("signals")[:5], # Only top 5 to save context
                "macro": state.get("macro"),
                "intel": state.get("intel"),
            }
            return json.dumps(lite_state, indent=2)
        except Exception:
            return "System state not available."

    def _handle_message(self, text: str):
        text_lower = text.lower().strip()
        
        # Admin Commands for Manual Risk Override
        if text_lower.startswith("/set_qty"):
            parts = text.split()
            if len(parts) == 3:
                symbol = parts[1].upper()
                try:
                    qty = int(parts[2])
                    from src.risk.active_portfolio import get_active_portfolio
                    ap = get_active_portfolio()
                    
                    found = False
                    # Search by symbol key prefix in case of Trade_ID appendages
                    for k, v in ap.open_positions.items():
                        if k.startswith(symbol + ":") or k == symbol:
                            v['quantity'] = qty
                            ap._save_state()
                            self._send_message(f"✅ Quantity for {symbol} updated to {qty}")
                            found = True
                            # Optional: Tell MERCURY broker to adjust if we want full sync
                            break
                    if not found:
                        self._send_message(f"❌ {symbol} not found in open positions.")
                except ValueError:
                    self._send_message("❌ Invalid quantity. Use: /set_qty RELIANCE 50")
            return
            
        if text_lower.startswith("/set_sl"):
            parts = text.split()
            if len(parts) == 3:
                symbol = parts[1].upper()
                try:
                    sl = float(parts[2])
                    from src.risk.active_portfolio import get_active_portfolio
                    ap = get_active_portfolio()
                    
                    found = False
                    for k, v in ap.open_positions.items():
                        if k.startswith(symbol + ":") or k == symbol:
                            # Use native API which handles JSON saving too
                            ap.adjust_stop_loss(k, sl)
                            self._send_message(f"✅ Stop loss for {symbol} updated to ₹{sl}")
                            found = True
                            break
                    if not found:
                        self._send_message(f"❌ {symbol} not found in open positions.")
                except ValueError:
                    self._send_message("❌ Invalid stop loss price. Use: /set_sl RELIANCE 2500.5")
            return

        if text_lower.startswith("/query"):
            query = text[6:].strip()
        else:
            query = text.strip()
            
        if not query:
            self._send_message("Please provide a question or use commands:\n/set_qty <SYMBOL> <QTY>\n/set_sl <SYMBOL> <PRICE>\nExample: Why did we lose money on TCS?")
            return
            
        self._send_message("🕵️‍♂️ AlphaZero is analyzing... (Commands available: /set_qty <SYM> <QTY>, /set_sl <SYM> <PRICE>)")
        
        state_str = self._get_system_state()
        
        prompt = f"""You are AlphaZero, an elite quantitative trading AI managing an Indian equities portfolio.
The user (your portfolio manager) is asking you a natural language query about the trading system.
Use the following real-time system state JSON to answer the query accurately, professionally, and concisely.
If the answer is not in the JSON, make a highly educated deduction based on standard quantitative finance principles.

System State:
{state_str}

User Query: {query}"""

        try:
            # We want short, punchy answers suitable for Telegram
            answer = self.llm.complete(
                prompt=prompt, 
                system="You are AlphaZero. Keep answers under 3 paragraphs. Use bullet points if listing multiple items.",
                max_tokens=600
            )
            if not answer:
                answer = "Error: LLM API is not configured or failed to respond. Please check your API keys."
            self._send_message(answer)
        except Exception as e:
            self._send_message(f"Error querying LLM: {str(e)}")

    def _send_message(self, text: str):
        try:
            requests.post(
                f"{self.api_url}/sendMessage",
                json={"chat_id": self.chat_id, "text": text},
                timeout=5
            )
        except Exception as e:
            logger.debug(f"Telegram send error: {e}")

    def _poll(self):
        while self.running:
            try:
                resp = requests.get(
                    f"{self.api_url}/getUpdates",
                    params={"offset": self.last_update_id + 1, "timeout": 30},
                    timeout=35
                )
                if resp.status_code == 200:
                    data = resp.json()
                    for update in data.get("result", []):
                        self.last_update_id = update["update_id"]
                        
                        msg = update.get("message", {})
                        chat = msg.get("chat", {})
                        
                        # Security: only respond to the authorized chat ID in .env
                        if str(chat.get("id", "")) == self.chat_id:
                            text = msg.get("text", "")
                            if text:
                                self._handle_message(text)
                                
            except requests.exceptions.Timeout:
                pass  # normal for long polling
            except Exception as e:
                logger.debug(f"Telegram poll error: {e}")
                time.sleep(5)
            time.sleep(1)

    def start(self):
        if not self.token or not self.chat_id:
            logger.info("Telegram Natural Language Bot disabled (Missing TELEGRAM_BOT_TOKEN or TELEGRAM_CHAT_ID).")
            return
            
        self.running = True
        logger.info("Telegram /query Bot starting - Natural Language Interface active")
        threading.Thread(target=self._poll, daemon=True, name="TelegramBotListener").start()
        
    def stop(self):
        self.running = False

def init_telegram_bot():
    """Helper purely to instantiate and return the bot if valid configs exist."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if token and chat_id:
        bot = TelegramQueryBot(token, chat_id)
        bot.start()
        return bot
    return None
