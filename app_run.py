import os
import re
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import requests
import yfinance as yf
import pandas as pd
from flask import Flask, request, abort

from linebot import LineBotApi, WebhookHandler
from linebot.exceptions import InvalidSignatureError
from linebot.models import MessageEvent, TextMessage, TextSendMessage


# =========================
# 0) Flask + LINE settings
# =========================
app = Flask(__name__)

CHANNEL_ACCESS_TOKEN = os.getenv("LINE_CHANNEL_ACCESS_TOKEN", "")
CHANNEL_SECRET = os.getenv("LINE_CHANNEL_SECRET", "")
OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")

line_bot_api = LineBotApi(CHANNEL_ACCESS_TOKEN)
handler = WebhookHandler(CHANNEL_SECRET)

# LINE 文字上限 5000，留緩衝
LINE_TEXT_LIMIT = 4800


# =========================
# 1) 股票名稱對照（你可以再加）
# =========================
# ✅ 強烈建議：台積電用 2330.TW，不要用 TSM（ADR）避免台灣交易日對不到
STOCK_MAP: Dict[str, str] = {
    # 台積電
    "台積電": "2330.TW",
    "TSMC": "2330.TW",
    "2330": "2330.TW",

    # 鴻海
    "鴻海": "2317.TW",
    "HonHai": "2317.TW",
    "Hon_Hai": "2317.TW",
    "2317": "2317.TW",

    # 聯發科
    "聯發科": "2454.TW",
    "MediaTek": "2454.TW",
    "2454": "2454.TW",

    # 聯電
    "聯電": "2303.TW",
    "UMC": "2303.TW",
    "2303": "2303.TW",

    # 瑞昱
    "瑞昱": "2379.TW",
    "Realtek": "2379.TW",
    "2379": "2379.TW",

    # 中華電信（台股）
    "中華電信": "2412.TW",
    "中華電": "2412.TW",
    "2412": "2412.TW",

    # 大立光
    "大立光": "3008.TW",
    "Largan": "3008.TW",
    "3008": "3008.TW",

    # 廣達
    "廣達": "2382.TW",
    "Quanta": "2382.TW",
    "2382": "2382.TW",

    # 光寶科
    "光寶科": "2301.TW",
    "光寶": "2301.TW",
    "LiteOn": "2301.TW",
    "2301": "2301.TW",

    # 緯穎
    "緯穎": "6669.TW",
    "WiWynn": "6669.TW",
    "6669": "6669.TW",
}


HELP_TEXT = (
    "📊 可用功能指令：\n"
    "1️⃣ 指定日期收盤價：台積電 2023-07-01（遇休市會自動用前一交易日）\n"
    "2️⃣ 平均（全期間）：台積電 平均（預設 2023-01-01～2024-12-31）\n"
    "3️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30\n"
    "4️⃣ 最近 N 天平均：台積電 最近10天\n"
    "5️⃣ 歷史極值：台積電 最高｜台積電 最低（2023-2024）\n"
    "6️⃣ 多股票同一天：台積電 鴻海 聯發科 2023-07-01\n"
    "🆘 輸入「幫助」隨時再看一次"
)


# =========================
# 2) 通用工具
# =========================
def safe_reply(text: str) -> str:
    text = (text or "").strip()
    if len(text) <= LINE_TEXT_LIMIT:
        return text
    return text[:LINE_TEXT_LIMIT] + "\n…（內容過長已截斷）"


def parse_date(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d")
    except Exception:
        return None


def resolve_symbol(name: str) -> Optional[str]:
    name = name.strip()
    return STOCK_MAP.get(name)


def yf_download(symbol: str, start: datetime, end: datetime) -> pd.DataFrame:
    """
    yfinance: end 為 exclusive，所以 caller 通常會 end+1day
    auto_adjust=False 確保 Close 欄位穩定
    """
    df = yf.download(
        symbol,
        start=start.strftime("%Y-%m-%d"),
        end=end.strftime("%Y-%m-%d"),
        progress=False,
        auto_adjust=False,
        actions=False,
        threads=False,
    )
    # 避免 MultiIndex 欄位造成 Close 找不到
    if hasattr(df.columns, "levels"):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    return df


# =========================
# 3) 台股即時成交價（TWSE 官方）
# =========================
def twse_realtime_price(stock_id: str) -> Optional[float]:
    """
    stock_id: '2330' 這種純數字
    回傳最新成交價 float
    """
    try:
        url = f"https://mis.twse.com.tw/stock/api/getStockInfo.jsp?ex_ch=tse_{stock_id}.tw"
        r = requests.get(url, timeout=6)
        data = r.json()

        if "msgArray" in data and len(data["msgArray"]) > 0:
            row = data["msgArray"][0]
            z = row.get("z", "")
            if z and z != "-" and z != "0":
                return float(z)
        return None
    except Exception:
        return None


# =========================
# 4) 歷史資料功能（2023-2024）
# =========================
DEFAULT_START = datetime(2023, 1, 1)
DEFAULT_END = datetime(2024, 12, 31)


def close_on_or_before(symbol: str, target: datetime) -> Tuple[Optional[datetime], Optional[float], str]:
    """
    找 target 當日收盤，若休市則往前找最近交易日。
    """
    start = target - timedelta(days=25)
    end = target + timedelta(days=1)

    df = yf_download(symbol, start, end + timedelta(days=1))
    if df is None or df.empty:
        return None, None, "查不到資料（可能代號錯誤或資料源暫時不可用）"

    df = df.sort_index()
    eligible = df[df.index <= target]
    if eligible.empty:
        return None, None, "該日期之前沒有交易資料"

    actual_dt = eligible.index[-1]
    close_val = eligible.iloc[-1].get("Close", None)

    try:
        close_val = float(close_val)
    except Exception:
        close_val = None

    if close_val is None:
        return None, None, "Close 欄位缺失或格式錯誤"

    note = ""
    if actual_dt.date() != target.date():
        note = "（該日休市，已改用前一交易日）"
    return actual_dt.to_pydatetime() if hasattr(actual_dt, "to_pydatetime") else actual_dt, close_val, note


def mean_close(symbol: str, start: datetime, end: datetime) -> Tuple[Optional[float], int, str]:
    df = yf_download(symbol, start, end + timedelta(days=2))
    if df is None or df.empty or "Close" not in df.columns:
        return None, 0, "查不到 Close 資料"
    close = df["Close"].dropna()
    if close.empty:
        return None, 0, "Close 無有效數值"
    close = close.astype(float)
    return float(close.mean()), int(close.shape[0]), ""


def recent_n_days_mean(symbol: str, n: int) -> Tuple[Optional[float], Optional[float], int, str]:
    """
    最近 n 個交易日平均（不是最近 n 個日曆日）
    回傳 (avg, latest, count, msg)
    """
    end = datetime.now()
    start = end - timedelta(days=220)  # 足夠涵蓋假日與缺漏
    df = yf_download(symbol, start, end + timedelta(days=2))
    if df is None or df.empty or "Close" not in df.columns:
        return None, None, 0, "查不到 Close 資料"

    close = df["Close"].dropna().astype(float)
    if close.shape[0] < n:
        return None, None, int(close.shape[0]), f"交易資料不足（目前只有 {close.shape[0]} 筆）"

    recent = close.iloc[-n:]
    avg = float(recent.mean())
    latest = float(close.iloc[-1])
    return avg, latest, n, ""


def extreme_close(symbol: str, start: datetime, end: datetime, mode: str) -> Tuple[Optional[float], Optional[datetime], str]:
    df = yf_download(symbol, start, end + timedelta(days=2))
    if df is None or df.empty or "Close" not in df.columns:
        return None, None, "查不到 Close 資料"
    close = df["Close"].dropna().astype(float)
    if close.empty:
        return None, None, "Close 無有效數值"

    if mode == "max":
        val = float(close.max())
        dt = close.idxmax()
    else:
        val = float(close.min())
        dt = close.idxmin()

    dt_py = dt.to_pydatetime() if hasattr(dt, "to_pydatetime") else dt
    return val, dt_py, ""


# =========================
# 5) GPT（OpenRouter）
# =========================
def ask_gpt(question: str) -> str:
    if not OPENROUTER_API_KEY:
        return "⚠️ 尚未設定 OPENROUTER_API_KEY，無法使用 AI 對話。"

    url = "https://openrouter.ai/api/v1/chat/completions"
    headers = {
        "Authorization": f"Bearer {OPENROUTER_API_KEY}",
        "Content-Type": "application/json",
    }
    payload = {
        "model": "openai/gpt-4o-mini",
        "messages": [
            {"role": "system", "content": "你是股票小幫手，可提供分析、新聞與趨勢。回答要簡潔、條列清楚。"},
            {"role": "user", "content": question},
        ],
        "temperature": 0.6,
    }

    try:
        resp = requests.post(url, json=payload, headers=headers, timeout=25)
        data = resp.json()

        if "error" in data:
            msg = data["error"].get("message", "未知錯誤")
            return f"❌ GPT API 錯誤：{msg}"

        if "choices" in data and len(data["choices"]) > 0:
            return data["choices"][0]["message"]["content"].strip()

        return "❌ GPT 回應格式無法解析，請稍後再試。"

    except Exception as e:
        return f"❌ GPT 程式錯誤：{str(e)}"


# =========================
# 6) 解析指令（7 大功能）
# =========================
def parse_recent_n(token: str) -> Optional[int]:
    token = token.replace(" ", "")
    m = re.match(r"^最近(\d+)(天)?$", token)
    if not m:
        return None
    n = int(m.group(1))
    return n if n > 0 else None


def process_text(user_text: str) -> str:
    user_text = user_text.strip()

    if not user_text:
        return HELP_TEXT

    if user_text in ("幫助", "help", "HELP", "？", "?"):
        return HELP_TEXT

    # ✅ 純數字 → 台股即時成交價（TWSE官方）
    if user_text.isnumeric():
        price = twse_realtime_price(user_text)
        if price is None:
            return "⚠️ 無法取得即時成交價，請確認代號是否正確（例如：2330、2603）"
        return f"📈 台股 {user_text} 最新成交價：{price:.2f}"

    # 拆 token（允許多股票）
    parts = [p for p in user_text.split() if p.strip()]

    # 也支援「台積電最近10天」這種沒空格
    if len(parts) == 1:
        m = re.match(r"^(.+?)(最近\d+天|最近\d+|平均|最高|最低|\d{4}-\d{2}-\d{2})$", parts[0])
        if m:
            parts = [m.group(1), m.group(2)]

    # 6️⃣ 多股票同一天：<股1> <股2> <股3> <日期>
    if len(parts) >= 2 and parse_date(parts[-1]) is not None:
        dt = parse_date(parts[-1])
        stock_names = parts[:-1]
        lines: List[str] = []

        for nm in stock_names:
            sym = resolve_symbol(nm)
            if not sym:
                lines.append(f"{nm}：⚠️ 我不認得這檔股票名稱")
                continue

            actual_dt, close_val, note = close_on_or_before(sym, dt)
            if close_val is None or actual_dt is None:
                lines.append(f"{nm} {dt.date()}：查不到資料")
            else:
                lines.append(f"{nm} {actual_dt.date()} 收盤：{close_val:.2f} {note}".rstrip())

        return "\n".join(lines)

    # 單檔：<股票> <指令...>
    if len(parts) >= 2:
        stock = parts[0]
        sym = resolve_symbol(stock)
        if not sym:
            return f"⚠️ 我不認得「{stock}」。請輸入「幫助」查看支援用法。"

        cmd = parts[1]

        # 1️⃣ 指定日期收盤：台積電 2023-07-01
        dt = parse_date(cmd)
        if dt:
            actual_dt, close_val, note = close_on_or_before(sym, dt)
            if close_val is None or actual_dt is None:
                return f"⚠️ 找不到 {stock} {dt.date()} 的股價紀錄"
            return f"{stock} {actual_dt.date()} 收盤價：{close_val:.2f} {note}".rstrip()

        # 2️⃣ 平均（全期間）：台積電 平均  (固定 2023-2024)
        if cmd == "平均" and len(parts) == 2:
            avg, n, msg = mean_close(sym, DEFAULT_START, DEFAULT_END)
            if avg is None:
                return f"⚠️ {stock} 平均計算失敗：{msg}"
            return f"{stock}（2023-2024，共{n}筆）平均收盤價：{avg:.2f}"

        # 3️⃣ 區間平均：台積電 平均 2023-01-01 2023-06-30
        if cmd == "平均" and len(parts) >= 4:
            start = parse_date(parts[2])
            end = parse_date(parts[3])
            if not start or not end:
                return "⚠️ 日期格式錯誤，請用 YYYY-MM-DD，例如：台積電 平均 2023-01-01 2023-06-30"
            if end < start:
                return "⚠️ 結束日期不能早於開始日期"

            avg, n, msg = mean_close(sym, start, end)
            if avg is None:
                return f"⚠️ {stock} 區間平均計算失敗：{msg}"
            return f"{stock}（{start.date()}～{end.date()}，共{n}筆）平均收盤價：{avg:.2f}"

        # 4️⃣ 最近 N 天平均：台積電 最近10天
        n = parse_recent_n(cmd)
        if n is not None:
            avg, latest, count, msg = recent_n_days_mean(sym, n)
            if avg is None or latest is None:
                return f"⚠️ {stock} 最近{n}天平均計算失敗：{msg}"
            delta = latest - avg
            sign = "高於" if delta >= 0 else "低於"
            return (
                f"{stock} 最近{n}天平均收盤價：{avg:.2f}\n"
                f"最新收盤：{latest:.2f}（{sign}平均 {abs(delta):.2f}）"
            )

        # 5️⃣ 歷史極值：最高 / 最低（2023-2024）
        if cmd in ("最高", "最低"):
            mode = "max" if cmd == "最高" else "min"
            val, dt2, msg = extreme_close(sym, DEFAULT_START, DEFAULT_END, mode)
            if val is None or dt2 is None:
                return f"⚠️ {stock} {cmd} 計算失敗：{msg}"
            return f"{stock}（2023-2024）歷史{cmd}收盤：{val:.2f}（{dt2.date()}）"

    # 其他：交給 GPT（即時 AI 對話）
    return ask_gpt(user_text)


# =========================
# 7) LINE webhook routes
# =========================
@app.route("/", methods=["GET"])
def health():
    return "OK", 200


@app.route("/callback", methods=["POST"])
def callback():
    signature = request.headers.get("X-Line-Signature", "")
    body = request.get_data(as_text=True)

    try:
        handler.handle(body, signature)
    except InvalidSignatureError:
        abort(400)

    return "OK", 200


@handler.add(MessageEvent, message=TextMessage)
def handle_message(event):
    user_text = event.message.text

    reply = process_text(user_text)
    reply = safe_reply(reply)

    line_bot_api.reply_message(
        event.reply_token,
        TextSendMessage(text=reply)
    )


# =========================
# 8) Run (Render needs PORT)
# =========================
if __name__ == "__main__":
    port = int(os.environ.get("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
