import os
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
import twstock

app = Flask(__name__)

# === Environment Variables ===
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
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是股票小幫手，可提供分析、新聞與趨勢。"},
            {"role": "user", "content": question}
        ]
    }

    try:
        r = requests.post(url, json=payload, headers=headers, timeout=20)
        data = r.json()

        # === 1. OpenRouter 回傳錯誤格式 ===
        if "error" in data:
            return f"❌ GPT API 錯誤：{data['error'].get('message', '未知錯誤')}"

        # === 2. choices 格式：message.content（OpenAI 格式） ===
        if "choices" in data:
            choice = data["choices"][0]
            # 有些模型用 message，有些用 messages
            if "message" in choice:
                return choice["message"]["content"]
            if "messages" in choice:
                return choice["messages"][0]["content"]

        # === 3. 無法解析（保底）===
        return "❌ GPT 回應格式無法解析，請稍後再試。"

    except Exception as e:
        return f"❌ GPT 程式錯誤：{str(e)}"


# ===== 即時股價 =====
def get_stock_price(stock_id):
    try:
        data = twstock.realtime.get(stock_id)
        if data["success"]:
            return data["realtime"]["latest_trade_price"]
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


# ===== 正確寫法：只加 MessageEvent =====
@handler.add(MessageEvent)
def handle_message(event):

    # 僅處理文字
    if not isinstance(event.message, TextMessage):
        return

    user_text = event.message.text.strip()

    # ★ 若輸入純數字 → 查股價
    if user_text.isnumeric():
        price = get_stock_price(user_text)
        if price:
            reply = f"📈 股票 {user_text} 最新成交價：{price}"
        else:
            reply = "⚠️ 無法取得股價，請確認代號是否正確（例如：2330、2603）"
        line_bot_api.reply_message(event.reply_token, TextSendMessage(text=reply))
        return

    # ★ 其他 → GPT 回答
    answer = ask_gpt(user_text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=answer))


@app.route("/")
def home():
    return "LineBot Running OK."


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
