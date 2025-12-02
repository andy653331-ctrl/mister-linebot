from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage
)
import requests
import os
import yfinance as yf

# -------------------------
# 🔐 讀取環境變數
# -------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENROUTER_API_KEY = os.getenv("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")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)

# -------------------------
# 🧠 GPT（OpenRouter） 
# -------------------------
def ask_gpt(text):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openrouter/openai/gpt-4.1-mini",
        "messages": [
            {"role": "user", "content": text}
        ]
    }

    try:
        res = requests.post(url, headers=headers, json=data, timeout=20)
        res_json = res.json()

        # 🔍 偵錯：回傳錯誤時顯示訊息
        if "choices" not in res_json:
            return f"❌ GPT 錯誤：{res_json}"

        return res_json["choices"][0]["message"]["content"]

    except Exception as e:
        return f"❌ GPT 回應錯誤：{str(e)}"


# -------------------------
# 📈 查台股（使用 yfinance）
# -------------------------
def get_stock_price(stock_id):
    try:
        ticker = yf.Ticker(f"{stock_id}.TW")
        price = ticker.fast_info["last_price"]

        if price:
            return f"📈 即時股價：{stock_id}\n最新成交價：{price}"
        else:
            return "查詢失敗，請確認股票代號是否正確。"

    except:
        return "無法取得股價，請確認代號是否正確。"


# -------------------------
# 📦 文字訊息處理
# -------------------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return 'OK'


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    # 如果輸入純數字 → 當作台股代號查詢
    if text.isdigit():
        reply = get_stock_price(text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 其他一般訊息 → GPT 回答
    answer = ask_gpt(text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(answer))


# -------------------------
# 🚀 主程式入口
# -------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
