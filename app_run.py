import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
import json

app = Flask(__name__)

# === Environment Variables ===
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# =====================================
#   📌 1. 取得台灣即時股價（改用 TWSE 官方 API）
# =====================================
def get_stock_price(stock_id):
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw"
        r = requests.get(url, timeout=6).json()

        if "msgArray" in r and len(r["msgArray"]) > 0:
            data = r["msgArray"][0]
            return data["z"]   # 最新成交價

        return None
    except:
        return None


# =====================================
#   📌 2. GPT（OpenRouter）
# =====================================
def ask_gpt(question):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是股票小幫手，可提供即時股價、產業趨勢與新聞解讀。"},
            {"role": "user", "content": question}
        ]
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=20)
        data = resp.json()

        # 新版 API 格式
        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"]

        # 回傳 API 錯誤訊息
        return f"❌ GPT API 錯誤：{data}"

    except Exception as e:
        return f"❌ GPT API 錯誤：{str(e)}"


# =====================================
#   📌 3. LINE Webhook
# =====================================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# =====================================
#   📌 4. 處理文字訊息
# =====================================
@handler.add(MessageEvent)
def handle_message(event):
    if not isinstance(event.message, TextMessage):
        return

    user_text = event.message.text.strip()

    # === 若是純數字 → 查股價 ===
    if user_text.isnumeric():
        price = get_stock_price(user_text)

        if price:
            reply = f"📈 股票 {user_text} 最新成交價：{price}"
        else:
            reply = "⚠ 無法取得股價，請確認代號是否正確（例：2330、2603）"

        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # === 其他全部交給 GPT ===
    answer = ask_gpt(user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=answer))


@app.route("/")
def home():
    return "LineBot Running OK."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
