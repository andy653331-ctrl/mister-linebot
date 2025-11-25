# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
from datetime import date
import requests
import twstock
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd
import PIL.Image
from bs4 import BeautifulSoup
from imgurpython import ImgurClient

from flask import Flask, request, abort
from linebot import LineBotApi, WebhookParser
from linebot.exceptions import InvalidSignatureError
from linebot.models import *

matplotlib.use('Agg')

app = Flask(__name__)

# -----------------------------------------
# 讀取 Render Environment Variables
# -----------------------------------------
line_bot_api = LineBotApi(os.getenv("Iz3erdDFz0nY3ykXJKCk2Z0Zd2Ues8vw3IGjYCrOwzyIo7yi2zHVM9COOXrQN7zojwupR/DHgXmE8u1hGwUHohcGZqwItOsNrOg8bNkGuHjnACM1+d05wOMBvXahPgisKLGusyeNU4sWslXJALehHgdB04t89/1O/w1cDnyilFU="))
parser = WebhookParser(os.getenv("a5e39152eb84b873667aac9b2d076ba0"))


# --------------------------------------------------
# BeautifulSoup 抓 Goodinfo
# --------------------------------------------------
def soup(url):
    headers = {
        "user-agent": "Mozilla/5.0"
    }
    resp = requests.get(url, headers=headers)
    resp.encoding = 'utf-8'
    return BeautifulSoup(resp.text, 'html.parser')


def convert(lst):
    return {lst[i]: lst[i + 1] for i in range(0, len(lst) - 1, 2)}


def upload_image(fn):
    client_id = '219e4677b4d2110'
    client_secret = '69f161c63fe23108f9f77498f72dd3c50c7adedd'

    client = ImgurClient(client_id, client_secret)
    image = client.upload_from_path(fn, anon=True)
    url = image['link']

    return ImageSendMessage(
        original_content_url=url,
        preview_image_url=url
    )


# --------------------------------------------------
# 1. Goodinfo 基本資料
# --------------------------------------------------
def crawl_for_stock_fundamental(event, stock_id):
    content = ""
    found_soup = soup("https://goodinfo.tw/StockInfo/StockDetail.asp?STOCK_ID=" + str(stock_id))

    company_name = found_soup.find("title").get_text().split()

    basic_info_tables = found_soup.find_all("table", {"class": "b1 p4_4 r10"})
    if not basic_info_tables:
        return None

    for t in basic_info_tables:
        if "產業別" in t.get_text():
            raw_info = t.find_all("td")

    info = []
    for i in raw_info[1:]:
        info.append(i.get_text().replace("\xa0", " "))
    info = convert(info)

    today = date.today()

    content += f"《公司基本資訊》\n{company_name[0]} {today}\n"
    content += f"公司名稱: {info['名稱']}\n"
    content += f"產業別: {info['產業別']}\n"
    content += f"面值: {info['面值']}\n"
    content += f"資本額: {info['資本額']} / 市值: {info['市值']}"

    return content


# --------------------------------------------------
# 2. TradingView 基本面（無 Selenium 版本）
# --------------------------------------------------
def tradingview_fundamental(stock_id):
    """
    TradingView 有一個隱藏 API 可以抓基本面資料：
    https://scanner.tradingview.com/taiwan/scan
    """

    url = "https://scanner.tradingview.com/taiwan/scan"

    payload = {
        "symbols": {
            "tickers": [f"TWSE:{stock_id}"],
            "query": {"types": []}
        },
        "columns": [
            "name",
            "close",
            "Recommend.All",
            "market_cap_basic",
            "price_earnings_ttm",
            "dividend_yield_recent"
        ]
    }

    headers = {"Content-Type": "application/json"}

    r = requests.post(url, json=payload, headers=headers)

    if r.status_code != 200:
        return None

    data = r.json()

    if "data" not in data or len(data["data"]) == 0:
        return None

    d = data["data"][0]["d"]

    name, close, rec, cap, pe, dy = d

    content = f"《TradingView 基本面》\n"
    content += f"名稱：{name}\n"
    content += f"收盤：{close}\n"
    content += f"評等：{rec}\n"
    content += f"市值：{cap}\n"
    content += f"P/E：{pe}\n"
    content += f"殖利率：{dy}"

    return content


# --------------------------------------------------
# 3. 即時股價
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
# 4. K 線圖
# --------------------------------------------------
def k_success(text, stock, event):
    fn = f"K_{text}.png"
    df = pd.DataFrame({"date": stock.date, "close": stock.close})

    df.plot(x="date", y="close")
    plt.title(f"[{stock.sid}]")
    plt.savefig(fn)
    plt.close()

    image_message = upload_image(fn)
    line_bot_api.reply_message(event.reply_token, image_message)


# --------------------------------------------------
# 5. 殖利率推薦
# --------------------------------------------------
def DY_sort(stock):
    s = stock.split()
    DY = float(s[3][:-1])
    price = 1 / float(s[2])
    return DY, price


def d_success(text):
    content = ""
    text = text.split()
    budget = float(text[0]) / 1000
    desire_DY = float(text[1])

    url = "https://stock.wespai.com/rate110"
    s = soup(url)
    trs = s.find("table", "display").tbody.find_all("tr")

    lst = []
    for tr in trs:
        t = tr.find_all("td")
        num = t[0].text
        name = t[1].text
        price = t[6].text
        DY = t[8].text
        if budget >= float(price) and desire_DY <= float(DY[:-1]):
            lst.append(f"{num} {name} {price} {DY}")

    lst = sorted(lst, reverse=True, key=DY_sort)

    if len(lst) >= 5:
        return "\n".join(lst[:5])
    elif len(lst) >= 1:
        return "\n".join(lst)
    else:
        return "沒有合適的標的"


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
                try:
                    stock = twstock.Stock(t)
                    k_success(t, stock, event)
                except:
                    send_text_message(event, "請輸入有效股號！")

            elif text.startswith("F"):
                t = text[1:]
                basic = crawl_for_stock_fundamental(event, t)
                tv = tradingview_fundamental(t)

                if not basic:
                    send_text_message(event, "查不到基本資料")
                else:
                    msg = basic + "\n\n" + (tv if tv else "無 TradingView 基本面資料")
                    send_text_message(event, msg)

            elif text.startswith("D"):
                send_text_message(event, d_success(text[1:]))

            else:
                send_text_message(event, "請輸入有效指令（P/K/F/D）。")

    return "OK"


if __name__ == "__main__":
    app.run()
