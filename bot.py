#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
بوت مراقبة العملات الرقمية - نسخة Render
يعمل كـ Background Worker
"""

import asyncio
import aiohttp
import os
import sys
from datetime import datetime
from typing import Dict, Optional

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler, 
    ContextTypes
)

# ==================== إعدادات البوت ====================
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")

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
            async with session.get(url) as response:
                if response.status == 200:
                    return await response.json()
                else:
                    print(f"API Error: {response.status}")
                    return None
    except Exception as e:
        print(f"Network Error: {e}")
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

async def send_alert(context: ContextTypes.DEFAULT_TYPE, coin_id: str, 
                     coin_symbol: str, old_price: float, 
                     new_price: float, percentage: float):
    message = format_alert_message(coin_id, coin_symbol, old_price, new_price, percentage)
    await context.bot.send_message(
        chat_id=ADMIN_CHAT_ID,
        text=message,
        parse_mode="Markdown"
    )
    print(f"[{datetime.now()}] ALERT: {coin_symbol} changed by {percentage:.2f}%")

async def check_prices(context: ContextTypes.DEFAULT_TYPE):
    print(f"[{datetime.now()}] Checking prices...")
    
    prices_data = await fetch_crypto_prices()
    if not prices_data:
        print("Failed to fetch prices")
        return
    
    for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
        if coin_id not in prices_data:
            continue
        
        current_price = prices_data[coin_id][VS_CURRENCY]
        
        if coin_id in price_history:
            old_price = price_history[coin_id]["price"]
            percentage = get_percentage_change(old_price, current_price)
            
            if abs(percentage) >= PRICE_CHANGE_THRESHOLD:
                await send_alert(context, coin_id, coin_symbol, old_price, current_price, percentage)
                price_history[coin_id] = {"price": current_price, "timestamp": datetime.now()}
            else:
                price_history[coin_id]["price"] = current_price
        else:
            price_history[coin_id] = {"price": current_price, "timestamp": datetime.now()}
            print(f"Initialized {coin_symbol} at ${current_price:,.2f}")

# ==================== أوامر البوت ====================

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
        f"✅ البوت يعمل على Render!\n\n"
        f"• نسبة التنبيه: {PRICE_CHANGE_THRESHOLD}%\n"
        f"• العملات: BTC, ETH\n\n"
        f"عند تغير السعر بنسبة {PRICE_CHANGE_THRESHOLD}% أو أكثر، ستتلقى تنبيهاً.",
        reply_markup=InlineKeyboardMarkup(keyboard),
        parse_mode="Markdown"
    )

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
            await query.edit_message_text("❌ تعذر جلب الأسعار.")
    
    elif query.data == "status":
        message = "📈 *حالة المراقبة:*\n\n"
        for coin_id, coin_symbol in CRYPTOCURRENCIES.items():
            if coin_id in price_history:
                price = price_history[coin_id]["price"]
                last_check = price_history[coin_id]["timestamp"].strftime("%H:%M:%S")
                message += f"• *{coin_symbol}*: ${price:,.2f} (آخر تحديث: {last_check})\n"
        await query.edit_message_text(message, parse_mode="Markdown")
    
    elif query.data == "change_threshold":
        global PRICE_CHANGE_THRESHOLD
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

# ==================== التشغيل ====================

async def main():
    print("🤖 Starting Crypto Alert Bot on Render...")
    
    if not TELEGRAM_TOKEN:
        print("❌ ERROR: TELEGRAM_TOKEN environment variable not set!")
        sys.exit(1)
    if not ADMIN_CHAT_ID:
        print("❌ ERROR: ADMIN_CHAT_ID environment variable not set!")
        sys.exit(1)
    
    print(f"✅ TOKEN loaded: {TELEGRAM_TOKEN[:10]}...")
    print(f"✅ ADMIN_ID: {ADMIN_CHAT_ID}")
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("price", price_command))
    application.add_handler(CallbackQueryHandler(button_handler))
    
    # بدء مهمة المراقبة الدورية
    application.job_queue.run_repeating(check_prices, interval=CHECK_INTERVAL_SECONDS, first=5)
    
    print(f"🤖 Bot is running! Monitoring {len(CRYPTOCURRENCIES)} cryptocurrencies...")
    print(f"📊 Alert threshold: {PRICE_CHANGE_THRESHOLD}%")
    print(f"⏱️ Check interval: {CHECK_INTERVAL_SECONDS} seconds")
    
    await application.initialize()
    await application.start()
    await application.updater.start_polling()
    
    # للحفاظ على التشغيل المستمر
    try:
        while True:
            await asyncio.sleep(3600)  # نام لمدة ساعة ثم استمر
    except KeyboardInterrupt:
        print("\n🛑 Bot stopped")
        await application.updater.stop()
        await application.stop()
        await application.shutdown()

if __name__ == "__main__":
    asyncio.run(main())
