from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage
import requests
import os

app = Flask(__name__)

# --- LINE TOKEN ---
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENROUTER_API_KEY = os.getenv("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")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)


# ============================
# 🔹 1. 即時台股股價（Yahoo Finance API）
# ============================
def get_stock_price(stock_id):
    url = f"https://query1.finance.yahoo.com/v8/finance/chart/{stock_id}.TW"

    try:
        res = requests.get(url, timeout=10).json()

        result = res["chart"]["result"][0]
        meta = result["meta"]
        current_price = meta["regularMarketPrice"]

        return f"📈 {stock_id} 即時股價\n最新成交價：{current_price}"

    except Exception:
        return "無法取得股價，請確認代號是否正確（例如：2330、2603）。"


# ============================
# 🔹 2. GPT + 上網查詢（Perplexity）
# ============================
def ask_gpt(query):
    url = "https://openrouter.ai/api/v1/chat/completions"

    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "perplexity/sonar",
        "messages": [
            {"role": "user", "content": query}
        ]
    }

    try:
        res = requests.post(url, headers=headers, json=data, timeout=20).json()

        if "choices" not in res:
            return f"❌ GPT 錯誤：{res}"

        return res["choices"][0]["message"]["content"]

    except Exception as e:
        return f"❌ GPT 回應錯誤：{str(e)}"


# ============================
# 🔹 3. LINE Webhook
# ============================
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# ============================
# 🔹 4. 訊息處理邏輯
# ============================
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    # 若使用者輸入股票代號（全數字）
    if text.isdigit():
        reply = get_stock_price(text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 其他文字丟給 GPT
    answer = ask_gpt(text)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(answer))


# ============================
# 🔹 5. 啟動服務（Render 用）
# ============================
if __name__ == "__main__":
    port = int(os.getenv("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
