from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, QuickReply, QuickReplyButton, MessageAction
)
import requests
import os
import twstock

# ---------------------------
# 🔐 讀取環境變數（Render 設定）
# ---------------------------
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("CHANNEL_SECRET")
OPENROUTER_API_KEY = os.getenv("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")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

app = Flask(__name__)

# ---------------------------
# 🧠 GPT 回應（使用 OpenRouter）
# ---------------------------
def ask_gpt(user_text):
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json"
    }

    data = {
        "model": "openrouter/openai/gpt-4.1-mini",
        "messages": [
            {"role": "user", "content": user_text}
        ]
    }

    try:
        res = requests.post("https://openrouter.ai/api/v1/chat/completions",
                            json=data, headers=headers, timeout=10)
        answer = res.json()["choices"][0]["message"]["content"]
        return answer
    except Exception as e:
        return f"❌ GPT 回應錯誤：{str(e)}"


# ---------------------------
# 📈 查台股即時股價
# ---------------------------
def get_stock_price(stock_id):
    try:
        stock = twstock.realtime.get(stock_id)
        if stock["success"]:
            price = stock["realtime"]["latest_trade_price"]
            return f"📈 {stock_id} 即時股價：{price}"
        else:
            return "查詢失敗，可能是無效的股票代號。"
    except:
        return "無法取得股價，請確認代號是否正確。"


# ---------------------------
# 🟦 Flex 主選單
# ---------------------------
def menu_flex():
    return FlexSendMessage(
        alt_text="主選單",
        contents={
            "type": "bubble",
            "hero": {
                "type": "image",
                "url": "https://i.imgur.com/abgEPBL.png",
                "size": "full",
                "aspectRatio": "20:13",
                "aspectMode": "cover"
            },
            "body": {
                "type": "box",
                "layout": "vertical",
                "spacing": "md",
                "contents": [
                    {
                        "type": "text",
                        "text": "選擇功能",
                        "weight": "bold",
                        "size": "xl"
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "🤖 AI 分析",
                            "text": "AI分析"
                        },
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "📂 追蹤清單",
                            "text": "追蹤清單"
                        },
                        "style": "primary"
                    },
                    {
                        "type": "button",
                        "action": {
                            "type": "message",
                            "label": "📰 股票新聞",
                            "text": "股票新聞"
                        },
                        "style": "primary"
                    }
                ]
            }
        }
    )


# ---------------------------
# ✔ LINE Webhook（不能有任何慢操作）
# ---------------------------
@app.route("/callback", methods=['POST'])
def callback():
    signature = request.headers['X-Line-Signature']
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# ---------------------------
# 🎯 文字訊息處理
# ---------------------------
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    text = event.message.text.strip()

    # ---------------------------
    # 主選單
    # ---------------------------
    if text in ["menu", "選單", "功能"]:
        line_bot_api.reply_message(event.reply_token, menu_flex())
        return

    # ---------------------------
    # 指令：AI 分析
    # ---------------------------
    if text == "AI分析":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            "請輸入你要分析的內容，例如：\n\n➡ 幫我分析台積電（2330）後市如何？"
        ))
        return

    # ---------------------------
    # 指令：查股價
    # 若輸入為純數字 → 判定為股票代號
    # ---------------------------
    if text.isdigit():
        reply = get_stock_price(text)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # ---------------------------
    # 指令：股票新聞（示範版）
    # ---------------------------
    if text == "股票新聞":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            "📰 最新股票新聞功能開發中…"
        ))
        return

    # ---------------------------
    # 指令：追蹤清單（示範版）
    # ---------------------------
    if text == "追蹤清單":
        line_bot_api.reply_message(event.reply_token, TextSendMessage(
            "📂 追蹤清單功能開發中…"
        ))
        return

    # ---------------------------
    # 🧠 其他文字 → 送 GPT
    # ---------------------------
    reply = ask_gpt(text)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(reply)
    )


# ---------------------------
# 🚀 主程式
# ---------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
