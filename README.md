# Trade Lab

本地模拟交易与策略研究工具。第一版面向沪深主板股票和境内股票 ETF，支持人工与规则账户对照、历史实验和复盘。

当前可用流程：从 AKShare 或 CSV 导入日线，逐日回放并记录人工决策，同时运行 20 日均线规则账户和同标的买入持有基准。每个实验保存自己的行情快照。

## 启动

需要 Python 3.12+、Node.js 22+。在仓库根目录运行：

```sh
python3 -m venv .venv
.venv/bin/pip install -r backend/requirements.txt
cd frontend && npm install && cd ..
.venv/bin/uvicorn app:app --app-dir backend --host 127.0.0.1 --port 8000
```

另开终端运行 `cd frontend && npm run dev`，然后访问 http://127.0.0.1:5173 。测试核心成交逻辑：`PYTHONPATH=backend python3 -m unittest backend/test_engine.py`。

CSV 需要 `date,open,high,low,close,volume` 六列（也支持对应中文列名），日期格式为 `YYYY-MM-DD`。首次实验只取最后 260 个交易日。

## 当前模拟假设

收盘后决策，下一交易日开盘按滑点价格模拟成交；买入使用可用资金内的整百数量，卖出全部持仓。费用和滑点在创建实验时固定为每笔成交额的 0.1%。停牌以成交量为零近似处理。

行情使用未经复权的价格，尚未计入分红送股、涨跌停排队及真实手续费明细。结果只用于验证研究流程，不能作为可信的完整历史收益。
证券类型目前由用户选择，尚未自动核实 ETF 的实际基金类别或股票所属板块。
