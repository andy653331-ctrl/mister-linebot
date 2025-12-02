import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
import twstock

app = Flask(__name__)

# === Read environment variables ===
CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)


# ===== GPT（OpenRouter） =====
def ask_gpt(question):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }
    payload = {
        "model": "openai/gpt-4.1-mini",
        "messages": [
            {"role": "system", "content": "你是一個股票小幫手，會分析股票、查詢新聞、提供投資知識。"},
            {"role": "user", "content": question}
        ]
    }

    try:
        response = requests.post(url, json=payload, headers=headers)
        data = response.json()
        return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"❌ GPT 錯誤：{str(e)}"


# ===== 股票最新價格 =====
def get_stock_price(stock_id):
    try:
        stock = twstock.realtime.get(stock_id)
        if stock["success"]:
            return float(stock["realtime"]["latest_trade_price"])
        return None
    except:
        return None


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


@handler.add(MessageEvent, MessageType=TextMessage)
def handle_message(event):

    user_text = event.message.text.strip()

    # === 如果是純數字 → 查股價 ===
    if user_text.isnumeric():
        price = get_stock_price(user_text)
        if price:
            reply = f"📈 股票 {user_text} 最新股價：{price}"
        else:
            reply = "無法取得股價，請確認代號是否正確（例如：2330，2603）"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # === 其他 → GPT 回答 ===
    answer = ask_gpt(user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=answer))


@app.route("/")
def home():
    return "Linebot Running"


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
