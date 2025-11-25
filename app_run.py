# -*- coding: utf-8 -*-
from __future__ import unicode_literals

import os
# from pymongo import MongoClient
from datetime import date

# ref: http://twstock.readthedocs.io/zh_TW/latest/quickstart.html#id2
import requests
import twstock
import matplotlib
import matplotlib.pyplot as plt
import pandas as pd

import PIL.Image
from bs4 import BeautifulSoup
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import NoSuchElementException
import time

from imgurpython import ImgurClient

from flask import Flask, request, abort
from linebot import (
    LineBotApi, WebhookParser, WebhookHandler
)
from linebot.exceptions import (
    InvalidSignatureError
)
from linebot.models import *

matplotlib.use('Agg')  # ref: https://matplotlib.org/faq/howto_faq.html

app = Flask(__name__)

# Channel access token
line_bot_api = LineBotApi(
    'kK3nS0J1mu0oDHuFs+W+CFjYLYhDmKOxK2tIaE4YdN7lw4lzhhEEuSqNUvjXimGjc+QW20XzcU+Xy8OID2CLN1AmpnkF6'
    '+wIgTN2DokyzpodhyYVMgAK/i2BGvxH+u+iS/hWBqeLIbqBGLzseGdY0QdB04t89/1O/w1cDnyilFU=')
# Channel secret
parser = WebhookParser('77fdb87ee576fcbee74ebebb7c4d416b')


# 用 Beautiful Soup 解析 Goodinfo HTML程式碼
def soup(url):
    headers = {
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) '
                      'Chrome/65.0.3325.181 Safari/537.36',
    }
    resp = requests.get(url, headers=headers)
    resp.encoding = 'utf-8'
    # 根據 HTTP header 的編碼解碼後的內容資料（ex. UTF-8）
    raw_html = resp.text

    return BeautifulSoup(raw_html, 'html.parser')


# 把 List convert 成 dict
def convert(lst):
    res_dct = {lst[i]: lst[i + 1] for i in range(0, len(lst) - 1, 2)}
    return res_dct


# 上傳圖檔至imgur並將圖片網址打包成一個訊息
def upload_image(fn):
    # -- upload
    # imgur with account: your.mail@gmail.com
    client_id = '219e4677b4d2110'
    client_secret = '69f161c63fe23108f9f77498f72dd3c50c7adedd'

    client = ImgurClient(client_id, client_secret)
    print("Uploading image... ")
    image = client.upload_from_path(fn, anon=True)
    print("Done")

    url = image['link']
    image_message = ImageSendMessage(
        original_content_url=url,
        preview_image_url=url
    )

    return image_message


# 在Goodinfo網站爬取公司基本資訊
def crawl_for_stock_fundamental(event, stock_id):
    content = ''
    found_soup = soup('https://goodinfo.tw/StockInfo/StockDetail.asp?STOCK_ID=' + str(stock_id))

    # 股票代碼 + 公司名稱
    company_name = found_soup.find("title").get_text().split()

    # 公司資訊
    basic_info_tables = found_soup.find_all("table", {"class": "b1 p4_4 r10"})
    if not basic_info_tables:
        content = "非常抱歉，目前暫無此股號相關基本資訊！"
        send_text_message(event, content)
        return

    for basic_info_table in basic_info_tables:
        # print(basic_info_table)
        if "產業別" in basic_info_table.get_text():
            raw_info = basic_info_table.find_all('td')

    info = []
    for i in raw_info[1:]:
        info.append(str(i.get_text()).replace("\xa0", " "))
    info = convert(info)

    today = date.today()

    # 將所需資訊及Title等放入List
    content += '《公司基本資訊》\n'
    content += '%s %s\n' % (
        company_name[0],
        today)
    content += '公司名稱: %s\n' % (
        info['名稱'])
    content += '產業別: %s\n' % (
        info['產業別'])
    content += '面值: %s\n' % (
        info['面值'])
    content += '資本額: %s / 市值: %s' % (
        info['資本額'],
        info['市值'])

    return content


# 依殖利率>價格排序
def DY_sort(stock):
    stock = stock.split()
    DY = float(stock[3][:-1])
    price = 1 / float(stock[2])
    return DY, price


def p_success(stock_rt, text):
    content = ''
    my_datetime = date.fromtimestamp(stock_rt['timestamp'] + 8 * 60 * 60)
    my_time = my_datetime.strftime('%H:%M:%S')

    content += '%s (%s) %s\n' % (
        stock_rt['info']['name'],
        stock_rt['info']['code'],
        my_time)
    content += '現價: %s / 開盤: %s\n' % (
        stock_rt['realtime']['latest_trade_price'],
        stock_rt['realtime']['open'])
    content += '最高: %s / 最低: %s\n' % (
        stock_rt['realtime']['high'],
        stock_rt['realtime']['low'])
    content += '量: %s\n' % (stock_rt['realtime']['accumulate_trade_volume'])

    stock = twstock.Stock(text)  # twstock.Stock('2330')
    content += '-----\n'
    content += '最近五日價格: \n'
    price5 = stock.price[-5:][::-1]
    date5 = stock.date[-5:][::-1]
    for i in range(len(price5)):
        if i == len(price5) - 1:
            content += '[%s] %s' % (date5[i].strftime("%Y-%m-%d"), price5[i])
        else:
            content += '[%s] %s\n' % (date5[i].strftime("%Y-%m-%d"), price5[i])

    return content


def k_success(text, stock, event):
    fn = 'K_%s.png' % text
    my_data = {'close': stock.close, 'date': stock.date, 'open': stock.open}
    df1 = pd.DataFrame.from_dict(my_data)

    df1.plot(x='date', y='close')
    plt.title('[%s]' % stock.sid)
    plt.savefig(fn)
    plt.close()

    image_message = upload_image(fn)
    line_bot_api.reply_message(
        event.reply_token,
        image_message
    )


def f_success(text, event):
    fn = 'F_%s.png' % text

    # 查詢公司基本資訊
    content = crawl_for_stock_fundamental(event, text)
    if not content:
        content = "請輸入有效股號或再試一次！"
        send_text_message(event, content)
    else:
        reply_lst = [TextSendMessage(text=content)]
        # 爬取tradingview網站的基本面資訊並將頁面截圖
        chrome_options = Options()
        windows_size = "1920,750"
        chrome_options.add_argument('--headless')
        chrome_options.add_argument("--window-size=%s" % windows_size)
        chrome_options.add_argument("--hide-scrollbars")
        chrome_options.binary_location = os.environ.get("GOOGLE_CHROME_BIN")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--no-sandbox")
        driver = webdriver.Chrome(executable_path=os.environ.get("CHROMEDRIVER_PATH"),
                                  chrome_options=chrome_options)
        driver.maximize_window()
        driver.get('https://tw.tradingview.com/symbols/TWSE-' + str(text))
        time.sleep(2)
        driver.find_element_by_class_name("text-oST7Udg3").click()
        try:
            ele = driver.find_element("xpath", '//div[@class="tv-feed-widget tv-feed-widget--fundamentals"]')
        except NoSuchElementException:
            content = "非常抱歉，目前暫無此股號相關資訊！"
            send_text_message(event, content)
            exit(0)

        start_height = ele.location["y"] - 10
        js = "scrollTo(0,%s)" % start_height
        driver.execute_script(js)  # 執行js
        time.sleep(0.5)
        driver.save_screenshot(fn)

        # 將基本面圖表從整頁截圖中切割
        img = PIL.Image.open(fp=fn)
        left = ele.location['x']
        # top = ele.location['y']
        right = ele.location['x'] + ele.size['width']
        # bottom = ele.location['y'] + ele.size['height']
        img = img.crop((left, 58, right, 730))
        img.save(fn)

        image_message = upload_image(fn)
        reply_lst.append(image_message)
        line_bot_api.reply_message(
            event.reply_token,
            reply_lst
        )

        driver.close()


# 爬殖利率
def d_success(text):
    content = ''
    text = text.split()
    budget = float(text[0]) / 1000
    desire_DY = float(text[1])
    url = 'https://stock.wespai.com/rate110'
    soup_found = soup(url)
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
    DY_sorted = sorted(DY_lst, reverse=True, key=DY_sort)
    if len(DY_sorted) >= 5:
        content = "\n".join(DY_sorted[:5])
    elif 5 > len(DY_sorted) >= 1:
        content = "\n".join(DY_sorted)
    elif not DY_sorted:
        content = "沒有合適的標的"
    return content


def send_text_message(event, content):
    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=content)
    )


@app.route("/callback", methods=['POST'])
def callback():
    # get X-Line-Signature header value
    signature = request.headers['X-Line-Signature']

    # get request body as text
    body = request.get_data(as_text=True)
    app.logger.info("Request body: " + body)

    # handle webhook body
    try:
        eve = parser.parse(body, signature)
    except InvalidSignatureError:
        print("Invalid signature. Please check your channel access token/channel secret.")
        abort(400)

    for event in eve:
        if isinstance(event, MessageEvent):
            text = event.message.text
            # 查詢即時股價
            if text.startswith('P'):
                text = text[1:]
                try:
                    stock_rt = twstock.realtime.get(text)
                    content = p_success(stock_rt, text)
                except KeyError:
                    content = "請輸入有效股號或再試一次！"

                send_text_message(event, content)

            # 查詢歷史股價圖表
            elif text.startswith('K'):
                text = text[1:]
                try:
                    stock = twstock.Stock(text)
                    k_success(text, stock, event)
                except KeyError:
                    content = "請輸入有效股號或再試一次！"
                    send_text_message(event, content)

            # 查詢公司基本資訊及基本面
            elif text.startswith('F'):
                text = text[1:]
                try:
                    twstock.Stock(text)
                    f_success(text, event)
                except KeyError:
                    content = "請輸入有效股號或再試一次！"
                    send_text_message(event, content)
            # 查詢殖利率推薦標的
            elif text.startswith('D'):
                text = text[1:]
                content = d_success(text)
                send_text_message(event, content)
            # 輸入無效指令的回應
            elif text != "幫助":
                content = "請輸入有效指令或輸入\"幫助\"來查看所有功能。"
                send_text_message(event, content)

    return 'OK'


if __name__ == "__main__":
    app.run()
