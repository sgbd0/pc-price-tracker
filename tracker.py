#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""电脑配件价格日报

每天抓取中关村在线(ZOL)商品页上的「参考报价」，存入本地历史文件，
生成 report.html / report.md 涨跌报告。

内置一个特别小的本地模型(Qwen2.5-0.5B, 约400MB, CPU即可运行)：
  1) 当页面改版、正则识别不到价格时，用小模型从网页文本里兜底识别价格；
  2) 每天用小模型给当日涨跌写一段中文摘要。
小模型不可用时自动退回纯规则模式，不影响日常更新。

用法:
  python tracker.py                 # 立即执行一次价格更新并生成报告
  python tracker.py list            # 查看监控清单
  python tracker.py add <URL> [名称]  # 添加监控商品
  python tracker.py remove <序号|名称> # 移除监控商品
  python tracker.py test <URL>      # 测试某个页面能否识别出价格
  python tracker.py model-setup     # 下载小模型(约400MB)
  python tracker.py report          # 只根据已有数据重新生成报告
"""
import argparse
import csv
import datetime as dt
import gzip
import html
import http.cookiejar
import json
import os
import re
import statistics
import sys
import time
import urllib.parse
import urllib.request

BASE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.join(BASE, "config.json")
DATA_DIR = os.path.join(BASE, "data")
LOGS_DIR = os.path.join(BASE, "logs")
MODELS_DIR = os.path.join(BASE, "models")
PRICES_CSV = os.path.join(DATA_DIR, "prices.csv")
JD_CSV = os.path.join(DATA_DIR, "jd_prices.csv")
JD_PER_RUN = 40          # 每轮抓多少款详情页的京东价
JD_CATS = {"cpu", "vga", "motherboard"}   # 实测仅这三类详情页带京东价模块
JD_RE = re.compile(r'_j_price_num">\s*￥\s*([\d,]+)')
LATEST_JSON = os.path.join(DATA_DIR, "latest.json")
REPORT_HTML = os.path.join(DATA_DIR, "report.html")
REPORT_MD = os.path.join(DATA_DIR, "report.md")

MODEL_FILE = "qwen2.5-3b-instruct-q4_k_m.gguf"
MODEL_URLS = [
    "https://hf-mirror.com/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/" + MODEL_FILE,
    "https://huggingface.co/Qwen/Qwen2.5-3B-Instruct-GGUF/resolve/main/" + MODEL_FILE,
]

UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

SEED_ITEMS = [
    {"name": "AMD 锐龙7 9800X3D", "url": "https://detail.zol.com.cn/cpu/index2113342.shtml"},
    {"name": "AMD 锐龙5 9600X", "url": "https://detail.zol.com.cn/cpu/index2018967.shtml"},
    {"name": "技嘉 RTX 5060 Ti GAMING OC 16G", "url": "https://detail.zol.com.cn/vga/index2130983.shtml"},
    {"name": "微星 RTX 5060 8G GAMING TRIO OC", "url": "https://detail.zol.com.cn/vga/index2128734.shtml"},
    {"name": "金百达银爵 16GB DDR4 3200", "url": "https://detail.zol.com.cn/memory/index1403967.shtml"},
    {"name": "金士顿 FURY 32GB DDR5 6000", "url": "https://detail.zol.com.cn/memory/index1629095.shtml"},
    {"name": "致态 TiPlus7100 1TB", "url": "https://detail.zol.com.cn/solid_state_drive/index1432187.shtml"},
    {"name": "西部数据 SN7100 1TB", "url": "https://detail.zol.com.cn/solid_state_drive/index2122758.shtml"},
    {"name": "技嘉 B650M GAMING WIFI", "url": "https://detail.zol.com.cn/motherboard/index2106519.shtml"},
    {"name": "航嘉 WD750K 全模组", "url": "https://detail.zol.com.cn/power/index1999767.shtml"},
]

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def log(msg):
    print(f"[{dt.datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------------------------------------------------------------- 配置

def load_config():
    if not os.path.exists(CONFIG_PATH):
        cfg = {
            "model": {"enabled": True, "file": os.path.join("models", MODEL_FILE),
                      "context_chars": 2000, "summary": True},
            "items": list(SEED_ITEMS),
        }
        save_config(cfg)
        return cfg
    with open(CONFIG_PATH, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    cfg.setdefault("model", {"enabled": True, "file": os.path.join("models", MODEL_FILE),
                             "context_chars": 2000, "summary": True})
    cfg.setdefault("items", [])
    return cfg


def save_config(cfg):
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)


# ---------------------------------------------------------------- 网页抓取

_opener = None


def get_opener():
    global _opener
    if _opener is None:
        jar = http.cookiejar.CookieJar()
        _opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(jar))
        _opener.addheaders = [
            ("User-Agent", UA),
            ("Accept", "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"),
            ("Accept-Language", "zh-CN,zh;q=0.9"),
            ("Referer", "https://www.zol.com.cn/"),
        ]
    return _opener


def fetch_url(url, timeout=25):
    """抓取 URL，返回解码后的文本。ZOL 会有一步跳转验证页，自动重试一次。"""
    opener = get_opener()
    for attempt in range(8):
        try:
            with opener.open(url, timeout=timeout) as r:
                raw = r.read()
                if (r.headers.get("Content-Encoding") or "").lower() == "gzip":
                    raw = gzip.decompress(raw)
        except Exception as e:
            if attempt == 2:
                raise RuntimeError(f"请求失败: {e}")
            time.sleep(1.5)
            continue
        head = raw[:2048].lower()
        charset = "utf-8"
        m = re.search(rb'charset\s*=\s*["\']?([\w-]+)', head)
        if m:
            charset = m.group(1).decode("ascii", "ignore")
        try:
            text = raw.decode(charset, "ignore")
        except LookupError:
            text = raw.decode("utf-8", "ignore")
        if "service.zol.com.cn/checking" in text or "service.zol.com.cn/checking" in raw[:600].decode("latin1", "ignore"):
            time.sleep(1.0 + attempt * 0.9)
            continue
        return text
    raise RuntimeError("页面反复跳转验证，抓取失败")


# ---------------------------------------------------------------- 价格识别(规则)

def strip_scripts(text):
    return re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text, flags=re.S | re.I)


def to_visible_text(html_text, limit):
    t = strip_scripts(html_text)
    t = re.sub(r"<[^>]+>", " ", t)
    t = html.unescape(t)
    t = re.sub(r"\s+", " ", t)
    return t[:limit]


def _num(s):
    try:
        return float(str(s).replace(",", ""))
    except ValueError:
        return None


def _walk_jsonld(node, out):
    if isinstance(node, dict):
        if "price" in node:
            p = _num(node["price"])
            if p and 10 <= p <= 500000:
                out.append(p)
        for v in node.values():
            _walk_jsonld(v, out)
    elif isinstance(node, list):
        for v in node:
            _walk_jsonld(v, out)


def extract_price_rules(html_text):
    """按优先级尝试多种规则，返回 (价格, 识别方式) 或 (None, None)。"""
    flat_ws = re.sub(r"\s+", " ", html_text)

    # 1) ZOL 详情页「参考报价」
    m = re.search(r"参考报价.{0,160}?￥\s*(?:</b>\s*<b[^>]*>\s*)?([0-9][0-9,\.]*)", flat_ws)
    if m:
        p = _num(m.group(1))
        if p:
            return p, "zol-参考报价"

    # 2) 结构化数据 JSON-LD
    for block in re.findall(r'<script[^>]*type="application/ld\+json"[^>]*>(.*?)</script>',
                            html_text, flags=re.S | re.I):
        try:
            out = []
            _walk_jsonld(json.loads(block), out)
            if out:
                return out[0], "json-ld"
        except Exception:
            pass

    # 3) 常见 meta / itemprop 标记
    m = re.search(r'itemprop="price"[^>]*content="([0-9][0-9,\.]*)"', flat_ws) or \
        re.search(r'content="([0-9][0-9,\.]*)"[^>]*itemprop="price"', flat_ws)
    if m:
        p = _num(m.group(1))
        if p:
            return p, "itemprop"

    # 4) 页面中第一个 ￥ 价格
    m = re.search(r"[￥¥]\s*([0-9][0-9,]{1,7}(?:\.[0-9]{1,2})?)", flat_ws)
    if m:
        p = _num(m.group(1))
        if p:
            return p, "货币符号"

    return None, None


# ---------------------------------------------------------------- 小模型

class ModelEngine:
    """特别小的本地模型。优先 llama-cpp-python 直接加载 GGUF；
    若机器上装了 Ollama 也可以借用；两者都不可用则退回纯规则模式。"""

    def __init__(self, mcfg):
        self.cfg = mcfg
        self.backend = None
        self.llm = None
        self.ollama_model = None

    @property
    def path(self):
        f = self.cfg.get("file") or os.path.join("models", MODEL_FILE)
        return f if os.path.isabs(f) else os.path.join(BASE, f)

    def load(self):
        if not self.cfg.get("enabled", True):
            return
        if os.path.exists(self.path):
            try:
                from llama_cpp import Llama
                log(f"加载本地小模型({MODEL_FILE})...")
                self.llm = Llama(model_path=self.path, n_ctx=4096, verbose=False,
                                 n_threads=min(os.cpu_count() or 4, 8))
                self.backend = "llama-cpp"
                log("小模型已就绪(llama-cpp)")
                return
            except Exception as e:
                log(f"llama-cpp 加载失败: {e}")
        if self._probe_ollama():
            self.backend = "ollama"
            log(f"小模型已就绪(借用本机 Ollama: {self.ollama_model})")
            return
        log("小模型不可用，本次仅用规则识别价格(不影响更新)")

    def _probe_ollama(self):
        try:
            with urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=3) as r:
                data = json.loads(r.read().decode("utf-8"))
            names = [m.get("name", "") for m in data.get("models", [])]
            pick = next((n for n in names if "qwen" in n.lower()), names[0] if names else None)
            if pick:
                self.ollama_model = pick
                return True
        except Exception:
            pass
        return False

    def available(self):
        return self.backend is not None

    def chat(self, system, user, max_tokens=96, temperature=0.1):
        if self.backend == "llama-cpp":
            prompt = (f"<|im_start|>system\n{system}<|im_end|>\n"
                      f"<|im_start|>user\n{user}<|im_end|>\n"
                      f"<|im_start|>assistant\n")
            out = self.llm(prompt, max_tokens=max_tokens, temperature=temperature,
                           stop=["<|im_end|>"], echo=False)
            return out["choices"][0]["text"].strip()
        if self.backend == "ollama":
            body = json.dumps({
                "model": self.ollama_model, "stream": False,
                "messages": [{"role": "system", "content": system},
                             {"role": "user", "content": user}],
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }).encode("utf-8")
            req = urllib.request.Request("http://127.0.0.1:11434/api/chat", data=body,
                                         headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return json.loads(r.read().decode("utf-8"))["message"]["content"].strip()
        return ""

    def extract_price(self, item_name, page_text):
        """小模型兜底识别价格。"""
        snippet = to_visible_text(page_text, self.cfg.get("context_chars", 2000))
        sys_p = "你是网页价格提取器，只输出JSON，不要任何解释。"
        usr_p = (f"商品名称: {item_name}\n网页文本:\n{snippet}\n\n"
                 "找出该商品当前的售价(数字, 单位元)。只输出 {\"price\": 数字}，找不到则输出 {\"price\": null}")
        text = self.chat(sys_p, usr_p, max_tokens=48)
        m = re.search(r"([0-9][0-9,]{1,7}(?:\.[0-9]{1,2})?)", text)
        if m:
            p = _num(m.group(1))
            if p and 50 <= p <= 500000:
                return p
        return None

    def summarize(self, changes, total_count):
        """生成今日涨跌摘要（只喂给模型有变化的商品）；失败返回 None。"""
        lines = [f"{c['name']} {'降价' if c['pct'] < 0 else '涨价'}："
                 f"{c['prev']:,.0f}元→{c['price']:,.0f}元，{'跌' if c['pct'] < 0 else '涨'}{abs(c['pct']):.1f}%。"
                 for c in changes[:5]]
        sys_p = "你是电商价格助手，用简体中文回答。"
        usr_p = (f"共监控{total_count}个配件，今天价格有变化的：\n" + "\n".join(lines) +
                 "\n请把以上变化概括成一句不超过50字的中文，说明哪个降、哪个涨。")
        try:
            out = self.chat(sys_p, usr_p, max_tokens=140, temperature=0.3).strip()
            if out and len(out) >= 8:
                if not re.search(r"[。！？…」']$", out):
                    # 输出在句中被截断，回退到最后一个完整句子
                    cut = max(out.rfind("。"), out.rfind("！"), out.rfind("？"))
                    out = out[:cut + 1] if cut >= 8 else ""
                if out:
                    return out
        except Exception as e:
            log(f"摘要生成失败: {e}")
        return None


# ---------------------------------------------------------------- 历史数据

def read_history():
    """返回 {name: [(date, price, time), ...]}，按日期+时间升序（每小时可能多条）。"""
    hist = {}
    if not os.path.exists(PRICES_CSV):
        return hist
    with open(PRICES_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                hist.setdefault(row["name"], []).append(
                    (row["date"], float(row["price"]), row.get("time", "")))
            except (KeyError, ValueError):
                continue
    for name in hist:
        hist[name].sort(key=lambda x: (x[0], x[2]))
    return hist


def append_price_rows(rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(PRICES_CSV)
    with open(PRICES_CSV, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "time", "name", "price", "method", "url"])
        for r in rows:
            w.writerow([r["date"], r["time"], r["name"], r["price"], r["method"], r["url"]])


def append_jd_rows(rows):
    os.makedirs(DATA_DIR, exist_ok=True)
    new_file = not os.path.exists(JD_CSV)
    with open(JD_CSV, "a", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        if new_file:
            w.writerow(["date", "time", "name", "price"])
        for r in rows:
            w.writerow([r["date"], r["time"], r["name"], r["price"]])


def read_jd_latest():
    """京东渠道：{name: 最新价}（文件按时间追加，后读到覆盖前读到）。"""
    latest = {}
    if not os.path.exists(JD_CSV):
        return latest
    with open(JD_CSV, "r", encoding="utf-8-sig", newline="") as f:
        for row in csv.DictReader(f):
            try:
                latest[row["name"]] = float(row["price"])
            except (KeyError, ValueError):
                continue
    return latest


# ---------------------------------------------------------------- 报告

UP_COLOR, DOWN_COLOR, FLAT_COLOR = "#d9412f", "#1f9d55", "#888888"


def sparkline_svg(values):
    if not values:
        return ""
    w, h, pad = 120, 30, 3
    if len(values) == 1 or max(values) == min(values):
        color = FLAT_COLOR
        pts = f"{pad},{h - pad} {w - pad},{h - pad}"
    else:
        color = UP_COLOR if values[-1] > values[0] else (DOWN_COLOR if values[-1] < values[0] else FLAT_COLOR)
        lo, hi = min(values), max(values)
        span = hi - lo
        pts = []
        for i, v in enumerate(values):
            x = pad + (w - 2 * pad) * i / (len(values) - 1)
            y = h - pad - (h - 2 * pad) * (v - lo) / span
            pts.append(f"{x:.1f},{y:.1f}")
        pts = " ".join(pts)
    return (f'<svg width="{w}" height="{h}" viewBox="0 0 {w} {h}">'
            f'<polyline points="{pts}" fill="none" stroke="{color}" stroke-width="1.6"/></svg>')


def build_report(rows, summary_text):
    """rows: [{'name','url','price','prev','pct','history':[(date,price)...], 'ok':bool}]"""
    now = dt.datetime.now()
    md = [f"# 电脑配件价格日报 ({now:%Y-%m-%d %H:%M})\n"]
    trs = []
    for r in rows:
        if not r["ok"]:
            line = f"| {r['name']} | 抓取失败 | - | - |"
            md.append(line)
            trs.append(f"<tr><td><a href='{html.escape(r['url'])}'>{html.escape(r['name'])}</a></td>"
                       f"<td class='fail' colspan='4'>抓取失败</td></tr>")
            continue
        if r["pct"] is None:
            diff_html, diff_md = "<span class='flat'>新增</span>", "新增"
        elif r["pct"] > 0.05:
            diff_html = f"<span class='up'>▲ +{r['pct']:.1f}%</span>"
            diff_md = f"▲ +{r['pct']:.1f}%"
        elif r["pct"] < -0.05:
            diff_html = f"<span class='down'>▼ {r['pct']:.1f}%</span>"
            diff_md = f"▼ {r['pct']:.1f}%"
        else:
            diff_html, diff_md = "<span class='flat'>— 持平</span>", "— 持平"
        md.append(f"| [{r['name']}]({r['url']}) | ¥{r['price']:,.0f} | "
                  f"{('¥%s' % format(r['prev'], ',.0f')) if r['prev'] else '-'} | {diff_md} |")
        trs.append(
            f"<tr><td><a href='{html.escape(r['url'])}' target='_blank'>{html.escape(r['name'])}</a></td>"
            f"<td class='price'>¥{r['price']:,.0f}</td>"
            f"<td>{('¥%s' % format(r['prev'], ',.0f')) if r['prev'] else '-'}</td>"
            f"<td>{diff_html}</td><td>{sparkline_svg([x[1] for x in r['history'][-14:]])}</td></tr>")

    md_html = ""
    if summary_text:
        md_html = f"<p class='summary'>🤖 {html.escape(summary_text)}</p>"
        md.insert(1, f"\n> 🤖 {summary_text}\n")

    page = f"""<!DOCTYPE html><html lang="zh"><head><meta charset="utf-8">
<title>配件价格日报 {now:%Y-%m-%d}</title><style>
body{{font-family:"Microsoft YaHei",system-ui,sans-serif;max-width:860px;margin:24px auto;padding:0 16px;color:#222;background:#fafafa}}
h1{{font-size:22px}} table{{border-collapse:collapse;width:100%;background:#fff;box-shadow:0 1px 4px rgba(0,0,0,.08)}}
th,td{{padding:9px 12px;border-bottom:1px solid #eee;text-align:left;font-size:14px}}
th{{background:#f2f4f7}} td.price{{font-weight:700;font-size:15px}}
a{{color:#2456c4;text-decoration:none}} a:hover{{text-decoration:underline}}
.up{{color:{UP_COLOR};font-weight:600}} .down{{color:{DOWN_COLOR};font-weight:600}} .flat{{color:#777}}
.fail{{color:#b00}} .summary{{background:#eef4ff;border:1px solid #d5e3ff;border-radius:8px;padding:10px 14px;font-size:14px}}
.footer{{color:#999;font-size:12px;margin-top:14px}}</style></head><body>
<h1>🖥️ 电脑配件价格日报 <small style="font-size:13px;color:#888">{now:%Y-%m-%d %H:%M}</small></h1>
{md_html}
<table><tr><th>商品</th><th>今日价</th><th>上次价</th><th>涨跌</th><th>近14天</th></tr>
{''.join(trs)}
</table>
<p class="footer">数据来源: 中关村在线(ZOL) 参考报价 · 本地小模型 Qwen2.5-0.5B 负责兜底识别与摘要 · 生成时间 {now:%Y-%m-%d %H:%M:%S}</p>
</body></html>"""
    with open(REPORT_HTML, "w", encoding="utf-8") as f:
        f.write(page)
    with open(REPORT_MD, "w", encoding="utf-8") as f:
        f.write("\n".join(md) + "\n")


# ---------------------------------------------------------------- 网页版数据

# 十大品类：ZOL 栏目 slug -> 中文名。每个品类的列表页自带该品类热门在售型号的参考报价，
# 一次请求即可更新整个品类（监控全量 ~400 款时无需逐个抓详情页）。
CATEGORIES = [
    ("cpu", "CPU"), ("motherboard", "主板"), ("memory", "内存"),
    ("vga", "显卡"), ("solid_state_drive", "固态硬盘"), ("hard_drives", "机械硬盘"),
    ("power", "电源"), ("case", "机箱"), ("cooling_product", "散热器"), ("lcd", "显示器"),
]

CAT_MAP = [("cpu", "CPU"), ("motherboard", "主板"), ("memory", "内存"), ("vga", "显卡"),
           ("solid_state", "固态硬盘"), ("hard_drives", "机械硬盘"), ("power", "电源"),
           ("case", "机箱"), ("cooling", "散热器"), ("lcd", "显示器")]

# 品类列表页结构：<a title="商品名" href="/slug/indexN.shtml"> … ￥价格
LIST_RE = re.compile(r'<a title="([^"]{4,80})" href="(/[a-z_]+/index\d+\.shtml)"'
                     r'[^>]*>.{0,120}?￥([\d,]+)')


def slug_of(url):
    m = re.search(r"zol\.com\.cn/([a-z_]+)/index\d+\.shtml", url)
    return m.group(1) if m else None


def item_path(url):
    m = re.search(r"/[a-z_]+/index\d+\.shtml", url)
    return m.group(0) if m else None


def category_of(url):
    for key, label in CAT_MAP:
        if key in url.lower():
            return label
    return "配件"


def public_url():
    """从 cloudflared 隧道日志里取当前公网地址（可能有）。"""
    log_file = os.path.join(LOGS_DIR, "tunnel.log")
    if os.path.exists(log_file):
        try:
            with open(log_file, "r", encoding="utf-8", errors="ignore") as f:
                found = re.findall(r"https://[a-z0-9-]+\.trycloudflare\.com", f.read())
            if found:
                return found[-1]
        except OSError:
            pass
    return None


def build_web_data():
    """汇总历史价格，供网页看板与静态导出使用。"""
    cfg = load_config()
    hist = read_history()
    jd_latest = read_jd_latest()
    today = dt.date.today().isoformat()
    items, all_dates, total_rows = [], set(), 0
    for it in cfg["items"]:
        raw_h = hist.get(it["name"], [])
        total_rows += len(raw_h)
        # 每小时更新后一天多条：按日期收敛为日线（保留最后一次），另保留今日分时
        by_date, by_hour = {}, {}
        for d, p, t in raw_h:
            by_date[d] = p
            all_dates.add(d)
            if d == today:
                by_hour[t[:2] or "00"] = p
        h = [(d, by_date[d]) for d in sorted(by_date)]
        prices = [p for _, p in h]
        recent = h[-90:]
        price = h[-1][1] if h else None
        prev = h[-2][1] if len(h) > 1 else None
        items.append({
            "name": it["name"], "url": it["url"], "cat": category_of(it["url"]),
            "price": price, "prev": prev,
            "pct": round((price - prev) / prev * 100, 2) if prev else None,
            "low": min(prices) if prices else None,
            "high": max(prices) if prices else None,
            "days": len(h),
            "jd": jd_latest.get(it["name"]),
            "today": [{"h": k + ":00", "p": v} for k, v in sorted(by_hour.items())],
            "history": [{"d": d, "p": p} for d, p in recent],
        })
    return {"updated": dt.datetime.now(dt.timezone(dt.timedelta(hours=8))).strftime("%Y-%m-%d %H:%M"),
            "public_url": public_url(),
            "stats": {"records": total_rows, "days": len(all_dates), "items": len(items)},
            "items": items}


def cmd_web_export(args):
    data = build_web_data()
    web_dir = os.path.join(BASE, "web")
    os.makedirs(web_dir, exist_ok=True)
    out = os.path.join(web_dir, "data.json")
    with open(out, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False)
    print(f"已导出网页数据: {out}")
    return 0


def cmd_serve(args):
    import webserver
    return webserver.main(args)


# ---------------------------------------------------------------- 核心流程

def fetch_item_price(item, model):
    url = item["url"]
    try:
        page = fetch_url(url)
    except Exception as e:
        log(f"✗ {item['name']}: {e}")
        return {"name": item["name"], "url": url, "ok": False, "method": "error"}
    price, method = extract_price_rules(page)
    if price is None and model and model.available():
        price = model.extract_price(item["name"], page)
        method = "小模型识别"
    if price is None:
        log(f"✗ {item['name']}: 页面抓到了但识别不到价格")
        return {"name": item["name"], "url": url, "ok": False, "method": "no-price"}
    return {"name": item["name"], "url": url, "ok": True, "price": price, "method": method}


def cmd_run(args):
    cfg = load_config()
    os.makedirs(LOGS_DIR, exist_ok=True)
    hist = read_history()
    model = None  # 小模型按需加载：仅当需要识别详情页或写摘要时

    today = dt.date.today().isoformat()
    now_t = dt.datetime.now().strftime("%H:%M:%S")

    # 1) 按品类分组：每个品类只抓一次列表页，即可拿到该品类全部监控型号的参考报价
    groups, customs = {}, []
    for it in cfg["items"]:
        s = slug_of(it["url"])
        if s:
            groups.setdefault(s, []).append(it)
        else:
            customs.append(it)
    list_prices = {}
    for s in groups:
        try:
            flat = re.sub(r"\s+", " ", fetch_url(f"https://detail.zol.com.cn/{s}/"))
            pairs = LIST_RE.findall(flat)
            for name, path, pr in pairs:
                p = _num(pr)
                if p:
                    list_prices.setdefault(path, (name, p))
            log(f"列表页[{s}]: {len(pairs)} 条")
        except Exception as e:
            log(f"✗ 列表页[{s}] 抓取失败: {e}")
        time.sleep(1.2)

    # 2) 逐个商品取价：列表页命中直接用；未命中的与自定义商品走详情页
    rows, detail_items = [], []
    for item in cfg["items"]:
        hit = list_prices.get(item_path(item["url"]))
        if hit:
            rows.append({"name": item["name"], "url": item["url"], "ok": True,
                         "price": hit[1], "method": "品类列表"})
        else:
            detail_items.append(item)
    log(f"列表页命中 {len(rows)} 款，需详情页 {len(detail_items)} 款")
    if detail_items:
        model = ModelEngine(cfg["model"])
        model.load()
        for item in detail_items:
            rows.append(fetch_item_price(item, model))

    # 3) 与历史比对并写库
    csv_rows = []
    for r in rows:
        prev_entries = [p for d, p, _t in hist.get(r["name"], []) if d < today]
        prev = prev_entries[-1] if prev_entries else None
        r["prev"] = prev
        r["pct"] = (r["price"] - prev) / prev * 100 if (r["ok"] and prev) else None
        if r["ok"]:
            csv_rows.append({"date": today, "time": now_t, "name": r["name"],
                             "price": r["price"], "method": r["method"], "url": r["url"]})
    fails = [r for r in rows if not r["ok"]]
    for r in fails[:5]:
        log(f"✗ {r['name']}")
    if len(fails) > 5:
        log(f"…另有 {len(fails) - 5} 款抓取失败")
    if csv_rows:
        append_price_rows(csv_rows)
    hist = read_history()
    for r in rows:
        r["history"] = hist.get(r["name"], [])

    # 4) 京东渠道：轮换抓一批详情页上的京东价（仅CPU/显卡/主板带此模块，借道ZOL避开京东反爬）
    zol_items = [it for it in cfg["items"] if slug_of(it["url"]) in JD_CATS]
    if zol_items:
        hour_idx = dt.datetime.now().hour
        block = [zol_items[(hour_idx * JD_PER_RUN + i) % len(zol_items)]
                 for i in range(min(JD_PER_RUN, len(zol_items)))]
        jd_rows, got = [], 0
        for it in block:
            try:
                flat = re.sub(r"\s+", " ", fetch_url(it["url"]))
                m = JD_RE.search(flat)
                if m:
                    p = _num(m.group(1))
                    if p:
                        jd_rows.append({"date": today, "time": now_t,
                                        "name": it["name"], "price": p})
                        got += 1
            except Exception:
                pass
            time.sleep(0.5)
        log(f"京东渠道: 本轮 {got}/{len(block)} 款")
        if jd_rows:
            append_jd_rows(jd_rows)

    summary = None
    tracked = [r for r in rows if r["ok"]]
    changed = [r for r in tracked if r["pct"] is not None and abs(r["pct"]) > 0.05]
    first_seen = [r for r in tracked if r["pct"] is None]
    if cfg["model"].get("summary", True):
        if changed:
            if model is None:
                model = ModelEngine(cfg["model"])
                model.load()
            if model.available():
                summary = model.summarize(changed, len(tracked))
        if summary is None and first_seen:
            summary = (f"开始跟踪 {len(first_seen)} 款配件，已记录首日价格；"
                       f"另有 {len(tracked) - len(first_seen)} 款续记。")
        elif summary is None and tracked:
            summary = f"今日 {len(tracked)} 款配件价格总体平稳，无明显涨跌。"
        if summary:
            log(f"摘要: {summary}")

    with open(LATEST_JSON, "w", encoding="utf-8") as f:
        json.dump({"updated": dt.datetime.now().isoformat(timespec="seconds"),
                   "items": [{"name": r["name"], "url": r["url"],
                              "price": r.get("price"), "prev": r.get("prev"),
                              "pct": round(r["pct"], 2) if r.get("pct") is not None else None,
                              "ok": r["ok"]} for r in rows]},
                  f, ensure_ascii=False, indent=2)

    report_rows = sorted(rows, key=lambda r: abs(r.get("pct") or 0), reverse=True)[:60]
    build_report(report_rows, summary)
    try:
        cmd_web_export(args)
    except Exception as e:
        log(f"网页数据导出失败: {e}")
    ok_n = len(tracked)
    log(f"完成: {ok_n}/{len(rows)} 款更新成功，报告已生成 data/report.html")
    return 0 if ok_n else 1


def cmd_refresh_catalog(args):
    """从 ZOL 十大品类列表页重建全量监控目录（保留自定义商品；同名历史沿用旧名称）。"""
    cfg = load_config()
    old_by_url = {it["url"]: it for it in cfg["items"]}
    new_items, seen = [], set()
    for slug, label in CATEGORIES:
        try:
            flat = re.sub(r"\s+", " ", fetch_url(f"https://detail.zol.com.cn/{slug}/"))
        except Exception as e:
            log(f"✗ {label}: {e}")
            continue
        n = 0
        for name, path, _pr in LIST_RE.findall(flat):
            url = "https://detail.zol.com.cn" + path
            if url in seen:
                continue
            seen.add(url)
            old = old_by_url.get(url)
            new_items.append({"name": (old or {}).get("name") or name, "url": url})
            n += 1
        log(f"✓ {label}: {n} 款")
        time.sleep(1.2)
    customs = [it for it in cfg["items"] if slug_of(it["url"]) is None]
    cfg["items"] = customs + new_items
    save_config(cfg)
    log(f"目录已刷新: ZOL 十大品类 {len(new_items)} 款 + 自定义 {len(customs)} 个，共 {len(cfg['items'])} 条监控")
    return 0


def cmd_list(args):
    cfg = load_config()
    if not cfg["items"]:
        print("监控清单为空，用 add 命令添加。")
        return 0
    for i, it in enumerate(cfg["items"], 1):
        print(f"{i:3d}. {it['name']}\n      {it['url']}")
    return 0


def guess_title(page):
    m = re.search(r"<title>\s*【(.+?)】", page)
    if m:
        return m.group(1).strip()
    m = re.search(r"<title>\s*([^<]{2,60})", page)
    return m.group(1).strip() if m else "未命名商品"


def cmd_add(args):
    cfg = load_config()
    url = args.url
    if not re.match(r"^https?://", url):
        url = "https://" + url
    if any(it["url"] == url for it in cfg["items"]):
        print("该商品已在监控清单中。")
        return 1
    print("正在抓取页面验证...")
    page = fetch_url(url)
    name = args.name or guess_title(page)
    price, method = extract_price_rules(page)
    cfg["items"].append({"name": name, "url": url})
    save_config(cfg)
    if price:
        print(f"✓ 已添加: {name}  当前识别价 ¥{price:,.0f} ({method})")
    else:
        print(f"✓ 已添加: {name}  (本次未能识别价格，明天更新时小模型会再尝试)")
    return 0


def cmd_remove(args):
    cfg = load_config()
    key = args.key
    items = cfg["items"]
    idx = None
    if key.isdigit() and 1 <= int(key) <= len(items):
        idx = int(key) - 1
    else:
        for i, it in enumerate(items):
            if key in it["name"]:
                idx = i
                break
    if idx is None:
        print(f"没有找到「{key}」，用 list 命令查看清单。")
        return 1
    removed = items.pop(idx)
    save_config(cfg)
    print(f"已移除: {removed['name']}")
    return 0


def cmd_test(args):
    cfg = load_config()
    page = fetch_url(args.url)
    price, method = extract_price_rules(page)
    if price:
        print(f"✓ 规则识别: ¥{price:,.0f}  (方式: {method})")
        return 0
    print("规则未能识别价格，尝试小模型...")
    model = ModelEngine(cfg["model"])
    model.load()
    if not model.available():
        print("✗ 小模型也不可用，无法识别。")
        return 1
    price = model.extract_price("测试商品", page)
    if price:
        print(f"✓ 小模型识别: ¥{price:,.0f}")
        return 0
    print("✗ 小模型也未能识别。")
    return 1


def cmd_report(args):
    cfg = load_config()
    hist = read_history()
    rows = []
    for it in cfg["items"]:
        h = hist.get(it["name"], [])
        rows.append({"name": it["name"], "url": it["url"], "ok": bool(h),
                     "price": h[-1][1] if h else None, "prev": h[-2][1] if len(h) > 1 else None,
                     "pct": (h[-1][1] - h[-2][1]) / h[-2][1] * 100 if len(h) > 1 else None,
                     "history": h})
    build_report(rows, None)
    print(f"报告已生成: {REPORT_HTML}")
    return 0


def cmd_model_setup(args):
    os.makedirs(MODELS_DIR, exist_ok=True)
    dest = os.path.join(MODELS_DIR, MODEL_FILE)
    if os.path.exists(dest) and os.path.getsize(dest) > 100 * 1024 * 1024:
        print(f"模型已存在: {dest}")
        return 0
    for url in MODEL_URLS:
        print(f"开始下载小模型 (约400MB): {url}")
        try:
            tmp = dest + ".part"
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r, open(tmp, "wb") as f:
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                t0 = time.time()
                while True:
                    chunk = r.read(1024 * 512)
                    if not chunk:
                        break
                    f.write(chunk)
                    done += len(chunk)
                    if time.time() - t0 > 2:
                        speed = done / (time.time() - t0) / 1024 / 1024
                        pct = f" {done * 100 // total}%" if total else ""
                        print(f"\r  {done / 1024 / 1024:6.1f}MB{pct}  {speed:.1f}MB/s", end="", flush=True)
            print()
            os.replace(tmp, dest)
            print(f"✓ 模型已下载: {dest}")
            return 0
        except Exception as e:
            print(f"下载失败({e})，尝试下一个源...")
    print("✗ 所有下载源均失败，请检查网络后重试。")
    return 1


def main():
    parser = argparse.ArgumentParser(description="电脑配件价格日报")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("run", help="立即更新一次价格并生成报告")
    sub.add_parser("list", help="查看监控清单")
    p_add = sub.add_parser("add", help="添加监控商品")
    p_add.add_argument("url")
    p_add.add_argument("name", nargs="?", default=None)
    p_rm = sub.add_parser("remove", help="移除监控商品(序号或名称)")
    p_rm.add_argument("key")
    p_test = sub.add_parser("test", help="测试某个页面能否识别价格")
    p_test.add_argument("url")
    sub.add_parser("model-setup", help="下载本地小模型")
    sub.add_parser("report", help="根据已有数据重新生成报告")
    sub.add_parser("refresh-catalog", help="从ZOL十大品类重建全量监控目录")
    sub.add_parser("web-export", help="导出网页看板数据(web/data.json)")
    p_serve = sub.add_parser("serve", help="启动本机网页看板服务")
    p_serve.add_argument("--port", type=int, default=None)
    p_serve.add_argument("--bind", default=None)

    args = parser.parse_args()
    cmd = args.cmd or "run"
    os.makedirs(DATA_DIR, exist_ok=True)
    return {"run": cmd_run, "list": cmd_list, "add": cmd_add, "remove": cmd_remove,
            "test": cmd_test, "model-setup": cmd_model_setup, "report": cmd_report,
            "refresh-catalog": cmd_refresh_catalog,
            "web-export": cmd_web_export, "serve": cmd_serve}[cmd](args)


if __name__ == "__main__":
    sys.exit(main())
