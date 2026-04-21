#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت مراقبة العملات الرقمية - نسخة Webhooks لـ Render Web Service
يعمل حتى مع الخطة المجانية
"""

import os
import sys
import asyncio
import aiohttp
import logging
from datetime import datetime
from typing import Dict, Optional
from flask import Flask, request, jsonify
from threading import Thread

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, Bot
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes, webhooks
)

# ==================== إعدادات التسجيل ====================
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ==================== إعدادات البوت ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
RENDER_URL = os.environ.get("RENDER_URL", "https://crypto-alert-bot.onrender.com")

# إعدادات المراقبة
CHECK_INTERVAL_SECONDS = 60
PRICE_CHANGE_THRESHOLD = 5.0

# العملات للمراقبة
CRYPTOCURRENCIES = {
    "bitcoin": "BTC",
    "ethereum": "ETH"
}

VS_CURRENCY = "usd"

# تخزين الأسعار
price_history: Dict[str, Dict] = {}

# ==================== التحقق من صحة الإعدادات ====================
if not TELEGRAM_TOKEN:
    logger.error("❌ TELEGRAM_TOKEN not set!")
    sys.exit(1)

if not ADMIN_CHAT_ID:
    logger.error("❌ ADMIN_CHAT_ID not set!")
    sys.exit(1)

logger.info(f"✅ Bot starting with ADMIN_ID: {ADMIN_CHAT_ID}")
logger.info(f"✅ Webhook URL: {RENDER_URL}")

# إنشاء التطبيق
application = Application.builder().token(TELEGRAM_TOKEN).build()
bot = Bot(token=TELEGRAM_TOKEN)

# ==================== Flask Web Server ====================
flask_app = Flask(__name__)

@flask_app.route('/webhook', methods=['POST'])
async def webhook():
    """استقبال التحديثات من تلغرام"""
    try:
        update_data = request.get_json()
        update = Update.de_json(update_data, application.bot)
        await application.process_update(update)
        return jsonify({"status": "ok"}), 200
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({"status": "error"}), 500

@flask_app.route('/health', methods=['GET'])
def health():
    """نقطة صحية لـ Render"""
    return jsonify({"status": "alive", "time": datetime.now().isoformat()}), 200

@flask_app.route('/', methods=['GET'])
def index():
    """الصفحة الرئيسية"""
    return "🤖 Crypto Alert Bot is running!", 200

# ==================== الدوال ====================

def get_percentage_change(old_price: float, new_price: float) -> float:
    if old_price == 0:
        return 0.0
    return ((new_price - old_price) / old_price) * 100.0

async def fetch_crypto_prices() -> Optional[Dict]:
    coins = ",".join(CRYPTOCURRENCIES.keys())
    url = f"https://api.coingecko.com/api/v3/simple/price?ids={coins}&vs_currencies={VS_CURRENCY}&include_24hr_change=true"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=30) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    logger.warning(f"API Error: {response.status}")
                    return None
    except Exception as e:
        logger.warning(f"Network Error: {e}")
        return None

def format_alert_message(coin_id: str, coin_symbol: str, old_price: float, 
                         new_price: float, percentage: float) -> str:
    direction = "🟢 صعود" if percentage > 0 else "🔴 هبوط"
    arrow = "📈" if percentage > 0 else "📉"
    formatted_percentage = f"{percentage:+.2f}%"
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    return f"""
{arrow} *تنبيه سعر {coin_symbol.upper()}* {arrow}

{direction}: {formatted_percentage}

💰 السعر السابق: ${old_price:,.2f}
💵 السعر الحالي: ${new_price:,.2f}
📊 نسبة التغير: {formatted_percentage}

🕐 الوقت: {now}
"""

async def check_and_send_alerts():
    """فحص الأسعار وإرسال تنبيهات (تعمل في الخلفية)"""
    global PRICE_CHANGE_THRESHOLD
    
    logger.info("Checking prices...")
    
    prices_data = await fetch_crypto_prices()
    if not prices_data:
        logger.warning("Failed to fetch prices")
        return
    
    for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
        if coin_id not in prices_data:
            continue
        
        current_price = prices_data[coin_id][VS_CURRENCY]
        
        if coin_id in price_history:
            old_price = price_history[coin_id]["price"]
            percentage = get_percentage_change(old_price, current_price)
            
            if abs(percentage) >= PRICE_CHANGE_THRESHOLD:
                message = format_alert_message(coin_id, coin_symbol, old_price, current_price, percentage)
                try:
                    await bot.send_message(
                        chat_id=ADMIN_CHAT_ID,
                        text=message,
                        parse_mode="Markdown"
                    )
                    logger.info(f"ALERT sent for {coin_symbol}: {percentage:.2f}%")
                except Exception as e:
                    logger.error(f"Failed to send alert: {e}")
                
                price_history[coin_id] = {"price": current_price, "timestamp": datetime.now()}
            else:
                price_history[coin_id]["price"] = current_price
                price_history[coin_id]["timestamp"] = datetime.now()
        else:
            price_history[coin_id] = {"price": current_price, "timestamp": datetime.now()}
            logger.info(f"Initialized {coin_symbol} at ${current_price:,.2f}")

async def periodic_check():
    """تشغيل الفحص الدوري"""
    while True:
        await check_and_send_alerts()
        await asyncio.sleep(CHECK_INTERVAL_SECONDS)

# ==================== أوامر البوت ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PRICE_CHANGE_THRESHOLD
    
    user_id = update.effective_user.id
    if str(user_id) != ADMIN_CHAT_ID:
        await update.message.reply_text("⚠️ هذا البوت خاص بصاحبه فقط.")
        return
    
    keyboard = [
        [InlineKeyboardButton("📊 السعر الحالي", callback_data="current_price")],
        [InlineKeyboardButton("⚙️ تعديل النسبة", callback_data="change_threshold")],
        [InlineKeyboardButton("📈 حالة المراقبة", callback_data="status")]
    ]
    
    await update.message.reply_text(
        f"🤖 *بوت مراقبة العملات الرقمية*\n\n"
        f"✅ البوت يعمل على Render (Web Service مجاني)!\n\n"
        f"• نسبة التنبيه: {PRICE_CHANGE_THRESHOLD}%\n"
        f"• العملات: BTC, ETH\n"
        f"• فترة الفحص: كل {CHECK_INTERVAL_SECONDS} ثانية\n\n"
        f"عند تغير السعر بنسبة {PRICE_CHANGE_THRESHOLD}% أو أكثر، ستتلقى تنبيهاً.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global PRICE_CHANGE_THRESHOLD
    
    query = update.callback_query
    await query.answer()
    
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        await query.edit_message_text("⚠️ غير مصرح.")
        return
    
    if query.data == "current_price":
        prices = await fetch_crypto_prices()
        if prices:
            message = "💰 *الأسعار الحالية:*\n\n"
            for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
                if coin_id in prices:
                    price = prices[coin_id][VS_CURRENCY]
                    change = prices[coin_id].get(f"{VS_CURRENCY}_24h_change", 0)
                    emoji = "📈" if change >= 0 else "📉"
                    message += f"• *{coin_symbol}*: ${price:,.2f} {emoji} ({change:+.2f}%)\n"
            await query.edit_message_text(message, parse_mode="Markdown")
        else:
            await query.edit_message_text("❌ تعذر جلب الأسعار حالياً.")
    
    elif query.data == "status":
        message = "📈 *حالة المراقبة:*\n\n"
        for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
            if coin_id in price_history:
                price = price_history[coin_id]["price"]
                last_check = price_history[coin_id]["timestamp"].strftime("%H:%M:%S")
                message += f"• *{coin_symbol}*: ${price:,.2f} (آخر تحديث: {last_check})\n"
        message += f"\n⚙️ نسبة التنبيه الحالية: {PRICE_CHANGE_THRESHOLD}%"
        await query.edit_message_text(message, parse_mode="Markdown")
    
    elif query.data == "change_threshold":
        keyboard = [
            [InlineKeyboardButton("2%", callback_data="set_2"), 
             InlineKeyboardButton("3%", callback_data="set_3"),
             InlineKeyboardButton("5%", callback_data="set_5")],
            [InlineKeyboardButton("7%", callback_data="set_7"), 
             InlineKeyboardButton("10%", callback_data="set_10")]
        ]
        await query.edit_message_text(
            f"⚙️ النسبة الحالية: {PRICE_CHANGE_THRESHOLD}%\nاختر نسبة جديدة:",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
    
    elif query.data.startswith("set_"):
        new_threshold = float(query.data.replace("set_", ""))
        PRICE_CHANGE_THRESHOLD = new_threshold
        await query.edit_message_text(f"✅ تم تعديل النسبة إلى {new_threshold}%")

async def price_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if str(update.effective_user.id) != ADMIN_CHAT_ID:
        return
    prices = await fetch_crypto_prices()
    if prices:
        message = "💰 *الأسعار الحالية:*\n\n"
        for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
            if coin_id in prices:
                price = prices[coin_id][VS_CURRENCY]
                message += f"• *{coin_symbol}*: ${price:,.2f}\n"
        await update.message.reply_text(message, parse_mode="Markdown")
    else:
        await update.message.reply_text("❌ تعذر جلب الأسعار.")

# ==================== التشغيل الرئيسي ====================

def run_flask():
    """تشغيل خادم Flask"""
    flask_app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 8080)))

async def setup_webhook():
    """إعداد webhook في تلغرام"""
    webhook_url = f"{RENDER_URL}/webhook"
    try:
        # إزالة أي webhook قديم
        await bot.delete_webhook()
        # تعيين webhook جديد
        await bot.set_webhook(webhook_url)
        logger.info(f"✅ Webhook set to: {webhook_url}")
        
        # إرسال رسالة ترحيب
        await bot.send_message(
            chat_id=ADMIN_CHAT_ID,
            text="🤖 *البوت يعمل الآن على Render Web Service!*\n\n✅ تم إعداد Webhook بنجاح.\n\nسأقوم بمراقبة أسعار BTC و ETH.",
            parse_mode="Markdown"
        )
    except Exception as e:
        logger.error(f"Failed to set webhook: {e}")

async def main():
    """الوظيفة الرئيسية"""
    logger.info("🤖 Starting Crypto Alert Bot on Render Web Service...")
    
    # إضافة معالجات الأوامر
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # إعداد webhook
    await setup_webhook()
    
    # بدء الفحص الدوري في الخلفية
    asyncio.create_task(periodic_check())
    
    logger.info(f"📊 Monitoring: {', '.join(CRYPTOCURRENCIES.values())}")
    logger.info(f"⚙️ Alert threshold: {PRICE_CHANGE_THRESHOLD}%")
    logger.info(f"⏱️ Check interval: {CHECK_INTERVAL_SECONDS}s")
    
    # تشغيل Flask في thread منفصل
    flask_thread = Thread(target=run_flask)
    flask_thread.start()
    
    logger.info("✅ Bot is running!")

if __name__ == "__main__":
    asyncio.run(main())
