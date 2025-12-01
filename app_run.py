import os
import requests
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import (
    MessageEvent, TextMessage, TextSendMessage,
    FlexSendMessage, QuickReply, QuickReplyButton, MessageAction
)

app = Flask(__name__)

# ==== LINE KEY ====
LINE_CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN")
LINE_CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET")

line_bot_api = LineBotApi(LINE_CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(LINE_CHANNEL_SECRET)

# ==== OPENROUTER KEY ====
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")
OPENROUTER_MODEL = "openai/gpt-4.1-mini"

# ==== 使用者追蹤清單 ====
user_watchlist = {}  # {user_id: [2330, 2603]}


# ============ ChatGPT（OpenRouter） ============
def ask_chatgpt(prompt):
    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_KEY}",
        "Content-Type": "application/json"
    }
    data = {
        "model": OPENROUTER_MODEL,
        "messages": [
            {"role": "system", "content": "你是智能 AI 股票助理"},
            {"role": "user", "content": prompt}
        ]
    }
    r = requests.post(url, headers=headers, json=data)
    res = r.json()
    try:
        return res["choices"][0]["message"]["content"]
    except:
        return "⚠ AI 回答發生錯誤，請稍後再試"


# ============ 查詢台股價格 ============
def get_stock_price(stock_id):
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw"
        res = requests.get(url).json()
        data = res["msgArray"][0]
        return f"📈 {data['n']}（{stock_id}）\n成交價：{data['z']}\n昨收：{data['y']}\n開盤：{data['o']}"
    except:
        return "❌ 查詢失敗，請確認股票代號是否正確"


# ============ 查詢新聞（Google News） ============
def get_stock_news(stock_id):
    url = f"https://news.google.com/rss/search?q={stock_id}+股票&hl=zh-TW&gl=TW&ceid=TW:zh-Hant"
    import feedparser
    feed = feedparser.parse(url)

    if len(feed.entries) == 0:
        return "沒有找到相關新聞"

    msg = f"📰 {stock_id} 最新新聞：\n\n"
    for e in feed.entries[:5]:
        msg += f"• {e.title}\n{e.link}\n\n"

    return msg


# ============ 主選單 ============
def main_menu():
    return TextSendMessage(
        text="請選擇功能：",
        quick_reply=QuickReply(
            items=[
                QuickReplyButton(action=MessageAction(label="AI 分析", text="AI分析")),
                QuickReplyButton(action=MessageAction(label="追蹤清單", text="追蹤清單")),
                QuickReplyButton(action=MessageAction(label="股票新聞", text="股票新聞")),
                QuickReplyButton(action=MessageAction(label="查詢股價", text="查股價")),
            ]
        )
    )


# ============ LINE Webhook ============
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK"


# ============ 處理訊息 ============
@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_id = event.source.user_id
    msg = event.message.text.strip()

    # 主選單
    if msg in ["hi", "你好", "選單", "menu"]:
        line_bot_api.reply_message(event.reply_token, main_menu())
        return

    # AI 分析
    if msg.startswith("AI分析"):
        reply = ask_chatgpt("請用專業方式分析股票市場：" + msg.replace("AI分析", ""))
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 查股價
    if msg.startswith("查股價"):
        line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入股票代號"))
        return

    if msg.isdigit() and len(msg) <= 5:
        reply = get_stock_price(msg)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 追蹤清單
    if msg == "追蹤清單":
        lst = user_watchlist.get(user_id, [])
        if lst == []:
            reply = "你的追蹤清單是空的"
        else:
            reply = "📌你的追蹤清單：\n" + "\n".join(lst)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    if msg.startswith("加入 "):
        stock_id = msg.replace("加入 ", "")
        user_watchlist.setdefault(user_id, []).append(stock_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(f"已加入：{stock_id}"))
        return

    # 股票新聞
    if msg.startswith("股票新聞"):
        line_bot_api.reply_message(event.reply_token, TextSendMessage("請輸入股票代號"))
        return

    if msg.startswith("news "):
        stock_id = msg.replace("news ", "")
        reply = get_stock_news(stock_id)
        line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))
        return

    # 不知道的指令 → 交給 ChatGPT
    reply = ask_chatgpt(msg)
    line_bot_api.reply_message(event.reply_token, TextSendMessage(reply))


# ============ Render 啟動 ============
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000)
