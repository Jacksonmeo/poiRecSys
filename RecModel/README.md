# T10e-2 独立纯净版

这是从原实验项目抽离出的、可离线独立运行的 T10e-2（High-confidence Unvisited Boost）工程。目录内已经包含 TKY 原始数据、T9 最优 checkpoint、train-only POI transition memory，以及数据处理、训练、验证集选参、测试评估和诊断所需的全部源码。

## 环境

- Python 3.10+
- 推荐 CUDA GPU（原环境为 PyTorch 2.7.1 + RTX 3070）
- Windows / Linux 均可；所有路径都相对当前工程解析

```bash
python -m venv .venv
# Windows: .venv\Scripts\activate
# Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt
```

Sentence-BERT 使用 `all-MiniLM-L6-v2`。首次运行时若本机 Hugging Face 缓存不存在，会自动联网下载一次；之后可直接使用缓存。

## 一键命令

```bash
# 约几十秒：检查原始数据处理、切分、词表、checkpoint、transition memory 和 rerank 核心逻辑
python run.py smoke

# 使用随包 checkpoint：重新构建特征，在 validation 验证已发布参数并执行 test
python run.py evaluate

# 完整复现原实验的 Stage A/B/C validation 网格搜索，再执行 test
python run.py evaluate-search

# 只从原始数据重新训练 T9
python run.py train --epochs 50

# 只从 train split 重新生成 transition memory
python run.py memory

# 完整实用链路：数据处理 -> T9 训练 -> memory -> 已发布参数 validation -> test/诊断/报告
python run.py full --epochs 50

# 完整研究复现链路（包含耗时较长的全量 validation 选参）
python run.py full-search --epochs 50
```

输出位于 `results/TKY/`，日志位于 `logs/TKY/`，checkpoint 位于 `checkpoints/TKY/`。
关键随包资产的完整性校验值记录在 `ARTIFACTS.sha256`。

## 严格实验协议

1. 轨迹按开始时间排序后做 80/10/10 temporal split。
2. vocab、Word2Vec、文本特征映射与所有 transition/geo/local memory 只使用 train split。
3. T10e-2 超参数只在 validation 上选择。
4. test 仅用于最终评估，输出 HR、NDCG、MRR、Seen/Unseen、flip cases 和诊断报告。

## 目录说明

```text
T10e_2_clean/
  run.py                         统一入口
  config.py                      固定的 TKY/T10e-2 配置
  dataset/                       原始 TKY CSV
  checkpoints/TKY/               可直接验证的 T9 checkpoint
  results/TKY/T10/               transition memory 与实验输出
  src/train_t9.py                T9 从零训练
  src/build_transition_memory.py train-only memory 构建
  src/t10e2.py                   T10e-2 val/test 主流程
  src/smoke_test.py              独立性与完整性快速检查
  src/{data,features,models}/     最小运行依赖
```

注意：所有 evaluate 命令都会重新训练 Word2Vec 并编码 POI 文本。`evaluate-search/full-search` 还会进行约 160 组 validation 推理，耗时明显更长。
