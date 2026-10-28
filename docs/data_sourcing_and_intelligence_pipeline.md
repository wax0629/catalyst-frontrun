# 全栈金融信息源选型、分类体系与自动化抓取工程链路规范 (Financial Data Sourcing, Selection Standards & Automation Pipeline)

> 档案定位：交易体系底层数据情报基建与工程化抓取手册  
> 最新更新时间：2026-10-28 12:05 CST  
> 规范等级：生产级标准规范 (Production-Grade Architecture)  
> 覆盖范围：宏观部委一手信源、7×24 毫秒级电报、交易所微观盘口、法定财报与机构研报数据

---

> [!WARNING]
> **【数据工程准则与零未来函数声明】**  
> 1. 本体系坚决杜绝“看后视镜炒股”：一切情报抓取必须严格记录一手事件发生的**原始客观时间戳（Point-in-Time）**，禁止在日K线回测中引用当日收盘后的任何宏观/财务/龙虎榜衍生指标；  
> 2. 本体系严控数据源合规与可用性：优先选用免 Token、不封 IP、零 Key 或官方公开的数据端点，并建立主备容灾（Failover）机制。

---

## 一、 信息源选型哲学与三大铁律 (Selection Philosophy & Iron Rules)

散户交易者与机构投资者的最大差距，往往不在于资金规模，而在于**“获取的是一手信号还是被二手自媒体稀释过的噪音”**。在建立信息获取体系时，我们设定了三大选型铁律：

```
================================================================================
【铁律 1：信源权威性与可溯源性（拒绝对手盘二道贩子的噪音）】
  - 核心要求：每一条能够触发标的观察池的资讯，必须能精准溯源到：
    a) 国务院 / 国家部委（发改委/工信部/交通部等）官方红头文件或司局长现场公开发言速记；
    b) 证监会 / 沪深北交易所 / 巨潮资讯网法定披露的上市公司公开发布公告与备案文号；
    c) 中国人民银行官方公开市场操作公告。
  - 排除对象：自媒体“突发！重磅！”标题党、未经核实的游资小作文、概念贴吧传言。
--------------------------------------------------------------------------------
【铁律 2：时钟差前瞻性（锁定 T0 萌芽静默期）】
  - 核心要求：信息到达时，对应板块与个股的盘面涨幅必须处于 0% ~ +2.5% 静默区间。
  - 逻辑硬核：任何在大涨 7%~10% 后全网刷屏的“利好”，本质上都是主力资金的兑现出货信号。我们只抓取“大盘恐慌、无人注意、但产业政策刚落地”的一手时差。
--------------------------------------------------------------------------------
【铁律 3：工程高可用与免依赖性（多源冗余与容灾）】
  - 核心要求：所有行情与数据抓取接口必须具备本地轻量化、无重量级付费商业终端依赖（如 Wind/Choice 商业授权）、网络断线自动降级切换能力。
================================================================================
```

---

## 二、 四级信息源全景矩阵与端点清单 (Four-Tier Source Matrix)

| 层级编号 | 数据层分类 | 核心覆盖内容 | 官方与第一主源 | 独立备用源 (Fallback) | 采集频率与延迟 |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Tier 1** | **一手官方政经与法定信披** | 部委产业试点、重大突发事件、央行货币操作、上市公司公告与三季报 | 工信部/发改委官网、中国人民银行、[巨潮资讯网 (CNINFO)](http://www.cninfo.com.cn/) | 交易所官方信披（沪深交易所上市公司信息平台） | 实时触发 / 盘前盘后扫描 (秒级) |
| **Tier 2** | **7×24 毫秒级机构电报** | 行业突发要闻、部委论坛现场速记、海外科技巨头动态 (Anthropic/OpenAI) | [财联社 7×24 电报](https://www.cls.cn/telegraph) (官方签名接口) | 东方财富 7×24 快讯、同花顺金融电报、华尔街见闻 | 7×24 实时长轮询 / 毫秒级推送 |
| **Tier 3** | **交易所微观盘口与行情** | 大盘指数、分时买卖五档、逐笔成交、MA5/MA20 均线、超大单资金流 | 腾讯金融行情集群 (`qt.gtimg.cn`)、通达信 (Mootdx TCP 直连) | 新浪财经行情源、东方财富 Push2 数据源 | 盘中 1~3 秒轮询 / 实时计算 |
| **Tier 4** | **基本面、研报与估值底线** | 连续 3 年财务三表、机构一致预期 (EPS)、历史 PE/PB 百分位、行业变迁 | 东方财富 ReportAPI、Baostock (历史估值与换手) | Tushare Pro 接口、申万行业分类数据库 | 每日盘后定时归档 (日频) |

---

## 三、 自动化获取工程链路与核心代码实现 (Pipeline & Code Architecture)

### 链路 1：7×24 机构级电报自动化获取与签名解析
* **工程逻辑**：财联社（CLS）是国内政经与产业政策发布速度最快的专业通讯社之一。其移动端/网页端电报流走 REST API，服务端对请求做了基于 MD5 与 SHA1 的参数验签。我们在本地逆向还原了签名算法，实现零 Key 高频抓取。
* **核心代码原型**：
```python
import time
import hashlib
import urllib.request
import urllib.parse
import json

def fetch_cls_telegraph(num_records=20):
    """
    抓取财联社 7x24 小时实时一手电报
    """
    timestamp = str(int(time.time()))
    params = {
        "app": "CxhAgent",
        "category": "",
        "last_time": timestamp,
        "os": "web",
        "rn": str(num_records),
        "sv": "8.4.6"
    }
    # 按照 query 键名字典序排序后拼接
    sorted_query = urllib.parse.urlencode(sorted(params.items()))
    # 核心验签: sign = md5(sha1(sorted_query))
    sha1_hash = hashlib.sha1(sorted_query.encode("utf-8")).hexdigest()
    sign = hashlib.md5(sha1_hash.encode("utf-8")).hexdigest()
    
    url = f"https://m.cls.cn/v1/roll/get_roll_list?{sorted_query}&sign={sign}"
    req = urllib.request.Request(url, headers={
        "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        "Referer": "https://www.cls.cn/telegraph"
    })
    
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        if data.get("errno") == 0:
            roll_list = data["data"].get("roll_data", [])
            results = []
            for item in roll_list:
                results.append({
                    "id": item.get("id"),
                    "title": item.get("title", ""),
                    "content": item.get("content", ""),
                    "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(item.get("ctime", 0))),
                    "subjects": [s.get("subject_name") for s in item.get("subjects", [])]
                })
            return results
    return []
```

---

### 链路 2：毫秒级全市场行情探测（腾讯金融集群引擎）
* **工程逻辑**：腾讯财经接口 `https://qt.gtimg.cn/q=...` 具备全球 CDN 极速响应、不封禁普通开发者 IP、支持多代码批量查询的特性。我们将其封装为 [`scripts/catalyst_radar.py`](file:///Users/apple/Projects/catalyst-frontrun/scripts/catalyst_radar.py) 的核心行情底层。
* **数据字段映射表**：
  * `parts[1]`：标的中文名称（如“均胜电子”）
  * `parts[2]`：标准证券代码（如“600699”）
  * `parts[3]`：当前最新撮合成交价
  * `parts[4]`：昨日收盘价
  * `parts[5]`：今日开盘价
  * `parts[32]`：最新涨跌幅（百分比，如 `+4.23`）
  * `parts[33]` / `parts[34]`：今日最高价 / 最低价
  * `parts[37]`：今日累计成交金额（万元，转换为亿元口径）
* **核心代码原型**（见 [`scripts/catalyst_radar.py`](file:///Users/apple/Projects/catalyst-frontrun/scripts/catalyst_radar.py#L28-L56)）：
```python
def fetch_quotes(code_list):
    """
    code_list: ['sh000001', 'sh600699', 'sz002212']
    """
    url = "https://qt.gtimg.cn/q=" + ",".join(code_list)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=5) as response:
        text = response.read().decode("gbk", errors="ignore")
        quotes = {}
        for line in text.strip().split(";"):
            if not line.strip():
                continue
            parts = line.split("~")
            if len(parts) > 37:
                code = parts[2]
                quotes[code] = {
                    "name": parts[1],
                    "code": code,
                    "price": float(parts[3]) if parts[3] else 0.0,
                    "change_pct": float(parts[32]) if parts[32] else 0.0,
                    "high": float(parts[33]) if parts[33] else 0.0,
                    "low": float(parts[34]) if parts[34] else 0.0,
                    "amount_yi": float(parts[37]) / 10000.0 if parts[37] else 0.0,
                    "time": parts[30]
                }
        return quotes
```

---

### 链路 3：微观盘口验真与均线量化门禁（通达信 TCP 直连）
* **工程逻辑**：利用开源协议（Mootdx）直接与国内顶级券商（如中信证券、华泰证券、招商证券）的通达信行情 L1/L2 主站建立底层 TCP 连接。通过 `tdx_client` 获取 1 分钟/5 分钟高频 K 线与日 K 线，直接在本地内存计算主力资金 Q 因子与均线结构。
* **门禁因子计算公式**：
  1. **5 日反转因子排雷**：
     $$R_{5d} = \frac{\text{Close}_t - \text{Close}_{t-5}}{\text{Close}_{t-5}} \times 100\%$$
     *若 $R_{5d} > 15\%$，门禁立即熔断，触发一票否决。*
  2. **聪明钱 Q 因子验真**：
     $$Q_{\text{smart}} = \frac{\sum_{k \in \text{大单分钟}} \text{Volume}_k}{\sum \text{Volume}_{\text{全天}}}$$
     *验证成交额放量中是否有低信噪比机构大单暗中吸筹（成交额阈值 $\ge 3$ 亿元）。*
  3. **均线生命线偏离度（Bias）**：
     $$\text{Bias}_{\text{MA5}} = \frac{\text{Price} - \text{MA5}}{\text{MA5}} \times 100\%$$
     *要求买入挂单点必须位于 MA5 均线上浮不超过 $0.3\%$ 的极低风险区。*

---

### 链路 4：法定公告与三季报穿透（巨潮资讯网 CNINFO 直连）
* **工程逻辑**：巨潮资讯网为中国证监会指定的上市公司法定信息披露网站。针对 10 月 25~31 日三季报窗口期的雷区排查，系统通过官方股票-机构动态映射表 `szse_stock.json` 自动解析出每只标的的 `orgId`，以 REST 端点拉取并检索公告标题与正文。
* **核心代码原型**：
```python
def fetch_cninfo_announcements(stock_code, org_id, page_num=1, page_size=15):
    """
    拉取上市公司正式公告 (三季报、分红、立案、减持)
    """
    url = "http://www.cninfo.com.cn/new/hisAnnouncement/query"
    data = {
        "pageNum": str(page_num),
        "pageSize": str(page_size),
        "column": "szse",
        "tabName": "fulltext",
        "plate": "",
        "stock": f"{stock_code},{org_id}",
        "searchkey": "",
        "secid": "",
        "category": "",
        "trade": "",
        "seDate": ""
    }
    req = urllib.request.Request(url, data=urllib.parse.urlencode(data).encode("utf-8"), headers={
        "User-Agent": "Mozilla/5.0",
        "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        "Referer": "http://www.cninfo.com.cn/new/commonUrl/pageOfSearch?url=disclosure/list/search"
    })
    with urllib.request.urlopen(req, timeout=8) as resp:
        res_json = json.loads(resp.read().decode("utf-8"))
        announcements = res_json.get("announcements", [])
        return [
            {
                "title": a.get("announcementTitle"),
                "date": a.get("announcementTime"),
                "url": "http://static.cninfo.com.cn/" + a.get("adjunctUrl")
            }
            for a in announcements
        ]
```

---

## 四、 降噪过滤器与真伪研判机制 (Noise Filtering & Fact Checking)

获取到原始海量数据后，系统必须执行严格的**信息清洗漏斗**，彻底阻断自媒体噪音污染交易系统：

```
                    【原始全网资讯流 (每日 5,000+ 条)】
                                  ↓
      [第一道滤网：关键词黑名单剔除 (Noise Blacklist)]
      • 剔除含“暴涨”、“主力意图曝光”、“突发重磅解读”、“千亿巨头沸腾”等词汇的自媒体二次创作
      • 剔除无明确采访对象、无红头文号、无具体官方发言人姓名的纯概念传闻
                                  ↓
      [第二道滤网：权威信源白名单验真 (Authority Whitelist)]
      • 必须命中工信部、发改委、交通部、央行、科技部、或巨潮公告代码
      • 记录第一手发生的精确时间戳 (例如：10-22 10:32:17)
                                  ↓
      [第三道滤网：时钟差与价格偏离度判定 (T0 Silence Zone)]
      • 计算抓取到消息瞬间对应标的的涨跌幅 ΔP
      • 若 ΔP >= +3.0%：说明市场早有人抢先一步，我方已无时差优势，坚决【放弃开仓】
      • 若 0.0% <= ΔP <= +2.5%：确认处于【T0 萌芽静默期】，立即将标的推入量化门禁池
```

---

## 五、 高可用容灾与防封降级矩阵 (Failover Matrix)

为了防止突发行情出现时因单个服务器超时或接口改版导致“双眼摸黑”，系统内置了全套降级备份机制：

| 业务类型 | 核心主源 (Primary) | 备用源 1 (Secondary) | 备用源 2 (Fallback) | 降级切换条件 |
| :--- | :--- | :--- | :--- | :--- |
| **实时行情快照** | 腾讯行情 (`qt.gtimg.cn`) | 新浪行情 (`hq.sinajs.cn`) | 通达信 TCP 节点直连 | HTTP 请求超时（> 3秒）或状态码非 200 |
| **历史K线与均线** | 通达信 Mootdx TCP | 腾讯分钟 K (`ifzq.gtimg.cn`) | Baostock 日K线本地缓存 | TCP 握手失败或解包为空数据 |
| **7×24 快讯流** | 财联社官方电报接口 | 东方财富 7×24 快讯流 | 自动化 WebSearch 实时探测 | 验签接口返回 `errno!=0` |
| **公司财报与公告** | 巨潮资讯网 CNINFO | 上交所 / 深交所官方公告披露页 | 东方财富公告库 PDF | 巨潮接口连接超时或维护 |

---

## 六、 关联工具与落地脚本

本规范中所涉及的抓取与计算逻辑，已完全落地在仓库代码中：
1. **行情与盘口雷达**：[`scripts/catalyst_radar.py`](file:///Users/apple/Projects/catalyst-frontrun/scripts/catalyst_radar.py)
2. **两层量化门禁筛选器**：[`scripts/quantamental_screener.py`](file:///Users/apple/Projects/catalyst-frontrun/scripts/quantamental_screener.py)
3. **全栈数据底层工具包**：[`simonlin1212__a-stock-data`](file:///Users/apple/Projects/trading/.agents/skills/simonlin1212__a-stock-data/SKILL.md)
4. **主控决策战报大账本**：[`docs/catalyst_timeline_and_battle_ledger.md`](file:///Users/apple/Projects/catalyst-frontrun/docs/catalyst_timeline_and_battle_ledger.md)
