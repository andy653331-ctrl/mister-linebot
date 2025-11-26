# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from datetime import date
import requests
import twstock
from flask import Flask, request, abort
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import *

app = Flask(__name__)

# -----------------------------------------
# 讀取 Render Environment Variables
# -----------------------------------------
line_bot_api = LineBotApi(os.getenv("Iz3erdDFz0nY3ykXJKCk2Z0Zd2Ues8vw3IGjYCrOwzyIo7yi2zHVM9COOXrQN7zojwupR/DHgXmE8u1hGwUHohcGZqwItOsNrOg8bNkGuHjnACM1+d05wOMBvXahPgisKLGusyeNU4sWslXJALehHgdB04t89/1O/w1cDnyilFU="))
parser = WebhookParser(os.getenv("a5e39152eb84b873667aac9b2d076ba0"))


# --------------------------------------------------
# 1. 即時股價查詢（P）
# --------------------------------------------------
def p_success(stock_rt, text):
    content = ""
    my_datetime = date.fromtimestamp(stock_rt["timestamp"] + 8 * 3600)
    my_time = my_datetime.strftime("%H:%M:%S")

    content += f"{stock_rt['info']['name']} ({stock_rt['info']['code']}) {my_time}\n"
    content += f"現價: {stock_rt['realtime']['latest_trade_price']} / 開盤: {stock_rt['realtime']['open']}\n"
    content += f"最高: {stock_rt['realtime']['high']} / 最低: {stock_rt['realtime']['low']}\n"
    content += f"量: {stock_rt['realtime']['accumulate_trade_volume']}\n-----\n最近五日價格:\n"

    stock = twstock.Stock(text)
    price5 = stock.price[-5:][::-1]
    date5 = stock.date[-5:][::-1]

    for i in range(5):
        content += f"[{date5[i].strftime('%Y-%m-%d')}] {price5[i]}"
        if i < 4:
            content += "\n"

    return content


# --------------------------------------------------
# 2. 公司基本面查詢（F）
# --------------------------------------------------
def crawl_for_stock_fundamental(event, stock_id):
    content = ""
    url = f"https://goodinfo.tw/StockInfo/StockDetail.asp?STOCK_ID={stock_id}"
    found_soup = BeautifulSoup(requests.get(url).text, 'html.parser')

    # 解析基本資料
    company_name = found_soup.find("title").get_text().split()
    basic_info_tables = found_soup.find_all("table", {"class": "b1 p4_4 r10"})
    if not basic_info_tables:
        return "查無資料"

    for t in basic_info_tables:
        if "產業別" in t.get_text():
            raw_info = t.find_all("td")
    
    info = {}
    for i in range(1, len(raw_info), 2):
        info[raw_info[i].get_text()] = raw_info[i+1].get_text().strip()

    today = date.today()

    content += f"《公司基本資訊》\n{company_name[0]} {today}\n"
    content += f"公司名稱: {info.get('名稱', 'N/A')}\n"
    content += f"產業別: {info.get('產業別', 'N/A')}\n"
    content += f"面值: {info.get('面值', 'N/A')}\n"
    content += f"資本額: {info.get('資本額', 'N/A')} / 市值: {info.get('市值', 'N/A')}"

    return content


# --------------------------------------------------
# 3. 殖利率推薦（D）
# --------------------------------------------------
def d_success(text):
    content = ""
    text = text.split()
    budget = float(text[0]) / 1000
    desire_DY = float(text[1])

    url = 'https://stock.wespai.com/rate110'
    soup_found = BeautifulSoup(requests.get(url).text, 'html.parser')
    target = soup_found.find("table", "display")
    trs = target.tbody.find_all("tr")

    DY_lst = []

    for tr in trs:
        tds = tr.find_all("td")
        numbers = tds[0].text
        names = tds[1].text
        prices = tds[6].text
        DY = tds[8].text
        if budget >= float(prices) and desire_DY <= float(DY[:-1]):
            DY_lst.append(f"{numbers} {names} {prices} {DY}")
    
    DY_sorted = sorted(DY_lst, reverse=True, key=lambda x: float(x.split()[3][:-1]))

    if len(DY_sorted) >= 5:
        content = "\n".join(DY_sorted[:5])
    elif 5 > len(DY_sorted) >= 1:
        content = "\n".join(DY_sorted)
    elif not DY_sorted:
        content = "沒有合適的標的"
    return content


# --------------------------------------------------
# 回覆文字
# --------------------------------------------------
def send_text_message(event, content):
    line_bot_api.reply_message(event.reply_token, TextSendMessage(text=content))


# --------------------------------------------------
# LINE Webhook
# --------------------------------------------------
@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers["X-Line-Signature"]
    body = request.get_data(as_text=True)

    try:
        events = parser.parse(body, signature)
    except InvalidSignatureError:
        abort(400)

    for event in events:
        if isinstance(event, MessageEvent):
            text = event.message.text

            if text.startswith("P"):
                t = text[1:]
                try:
                    stock_rt = twstock.realtime.get(t)
                    content = p_success(stock_rt, t)
                except:
                    content = "請輸入有效股號！"
                send_text_message(event, content)

            elif text.startswith("K"):
                t = text[1:]
                content = "功能已取消，請使用其他查詢"
                send_text_message(event, content)

            elif text.startswith("F"):
                t = text[1:]
                content = crawl_for_stock_fundamental(event, t)
                send_text_message(event, content)

            elif text.startswith("D"):
                content = d_success(text[1:])
                send_text_message(event, content)

            else:
                send_text_message(event, "請輸入有效指令（P/K/F/D）。")

    return "OK"


if __name__ == "__main__":
    app.run()
