"""Transformer Next POI 实验的集中配置文件。"""

from pathlib import Path

# 修改此字段即可切换整个数据处理与实验流程。
DATASET = "TKY"  # "NYC" 或 "TKY"

PROJECT_ROOT = Path(__file__).resolve().parent

DATASET_FILES = {
    "NYC": PROJECT_ROOT / "dataset" / "dataset_TSMC2014_NYC.csv",
    "TKY": PROJECT_ROOT / "dataset" / "dataset_TSMC2014_TKY.csv",
}

DATA_PATH = str(DATASET_FILES[DATASET])
SAVE_DIR = str(PROJECT_ROOT / "results" / DATASET)
CHECKPOINT_DIR = str(PROJECT_ROOT / "checkpoints" / DATASET)
LOG_DIR = str(PROJECT_ROOT / "logs" / DATASET)

# 数据预处理
SEQ_LEN = 10
MIN_POI_CHECKINS = 10
MIN_USER_CHECKINS = 10
TRAIN_RATIO = 0.80
VAL_RATIO = 0.10

# 特征维度
VENUE_EMB_DIM = 64
CAT_EMB_DIM = 16
BEHAV_EMB_DIM = 128
BEHAV_PROJ_DIM = 64
TEXT_EMB_DIM = 384
TEXT_PROJ_DIM = 64

# Word2Vec 行为语义嵌入
W2V_WINDOW = 3
W2V_EMB_DIM = 128
W2V_N_NEGS = 5
W2V_BATCH_SIZE = 2048
W2V_EPOCHS = 10
W2V_LR = 0.001

# Sentence-BERT 文本语义嵌入
SBERT_MODEL = "all-MiniLM-L6-v2"
SBERT_BATCH_SIZE = 256
SBERT_LOCAL_FILES_ONLY = False

# Transformer 模型
D_MODEL = 128
N_HEADS = 2
N_LAYERS = 2
FF_DIM = 256
DROPOUT = 0.1
FC_DROPOUT = 0.3

# Dynamic Fusion 配置
FUSION_TYPE = "static"  # "static" 或 "dynamic"
GATE_HIDDEN = 64  # Dynamic Fusion Gate MLP 隐藏层大小

# T8 Long-Short Fusion 配置
MAX_USER_HISTORY = 100  # 长期用户历史最大 POI 数量
LONG_PREF_TYPE = "attention"  # "attention" 或 "mean"

# T9 Causal Memory Fusion 配置
MAX_CAUSAL_HISTORY = 50  # 因果长期记忆最大 POI 数量（比 T8 小，因为 causal 过滤后更少）
CAUSAL_PREF_TYPE = "attention"  # "attention" 或 "mean"

# GeoBias 配置
GEO_GAMMA_INIT = 0.1  # 可学习 gamma 的初始 raw 值（经 softplus 后 ≈ 0.744）

# Gated GeoBias 配置（T6a）
GATED_GEO_GAMMA_INIT = -3.0  # softplus(-3.0) ≈ 0.0486，弱初始化避免过度惩罚
GATED_GEO_MAX_PENALTY = 1.0  # 惩罚上限，避免距离项压过语义 logits

# Distance Feature Scoring 配置（T7）
DISTANCE_BUCKET_DIM = 16      # 距离分桶嵌入维度
TRANSITION_DIM = 16           # 类别转移嵌入维度

# 训练配置
BATCH_SIZE = 512
LR = 0.001
EPOCHS = 50
GRAD_CLIP = 1.0
PATIENCE = 15
SCHEDULER_FACTOR = 0.5
SCHEDULER_PATIENCE = 5
SEED = 42
NUM_WORKERS = 0

# 模型消融变体与报告顺序
# 以下定义各消融变体的特征开关组合，用于对比不同特征组合对推荐性能的影响。
# REPORT_ORDER 控制变体在实验报告中的展示顺序。
REPORT_ORDER = [
    "T5_Fusion_Dynamic",
    "T8_LongShort_DynamicFusion",
]

MODEL_VARIANTS = [
    {
        "name": "T5_Fusion_Dynamic",
        "use_category": True,
        "use_behav": True,
        "shuffle_behav": False,
        "use_text": True,
        "fusion_type": "dynamic",
        "scoring_type": "linear",
        "description": "+ Behavior + BERT 融合 (Dynamic Gate)",
    },
    {
        "name": "T8_LongShort_DynamicFusion",
        "use_category": True,
        "use_behav": True,
        "shuffle_behav": False,
        "use_text": True,
        "fusion_type": "dynamic",
        "scoring_type": "linear",
        "use_long_pref": True,
        "long_pref_type": "attention",
        "description": "T5 + Long-term User Preference (Attention pool over train history, max 100)",
    },
]

# 前五个条目沿用原始 NYC 训练顺序。这样可以保持旧有消融指标
# 的可复现性，同时为新要求的六行报告增加仅 ID 的基线。
# NYC_VERIFICATION_VARIANTS = [
#     MODEL_VARIANTS[1],
#     MODEL_VARIANTS[3],
#     MODEL_VARIANTS[4],
#     MODEL_VARIANTS[2],
#     MODEL_VARIANTS[5],
#     MODEL_VARIANTS[0],
# ]

# 旧版 NYC 模型名称到新版命名的映射表。
# 用于将早期实验报告中的旧名称转换为当前统一命名体系，确保结果可追溯。
LEGACY_NYC_MODEL_MAP = {
    "T2_Category": "T0_ID_only",
    "T3b_Behavioral": "T1_Behavioral",
    "T3b_Shuffle": "T2_Behavioral_Shuffled",
    "T3_BERT": "T3_Text",
    "T4_Fusion": "T4_Fusion",
}


def dataset_file(dataset: str = DATASET) -> str:
    """返回指定数据集对应的 CSV 文件路径。

    根据数据集名称（"NYC" 或 "TKY"）从 DATASET_FILES 字典中
    查找对应的原始数据文件路径。

    参数:
        dataset: 数据集名称，默认为模块顶部的 DATASET 常量。

    返回:
        数据文件的绝对路径字符串。
    """
    return str(DATASET_FILES[dataset])


def save_dir(dataset: str = DATASET) -> str:
    """返回指定数据集的结果保存目录路径。

    所有模型输出、评估指标和实验结果文件都将存储在此目录下，
    按数据集隔离以避免混淆。

    参数:
        dataset: 数据集名称，默认为 DATASET 常量。

    返回:
        结果目录的绝对路径字符串。
    """
    return str(PROJECT_ROOT / "results" / dataset)


def checkpoint_dir(dataset: str = DATASET) -> str:
    """返回指定数据集的模型检查点保存目录路径。

    训练过程中定期保存的模型权重存放在此目录，支持中断恢复和
    最优模型选回。

    参数:
        dataset: 数据集名称，默认为 DATASET 常量。

    返回:
        检查点目录的绝对路径字符串。
    """
    return str(PROJECT_ROOT / "checkpoints" / dataset)


def log_dir(dataset: str = DATASET) -> str:
    """返回指定数据集的日志文件保存目录路径。

    TensorBoard 日志和训练过程中的文本日志均写入此目录，
    便于按数据集分别追踪实验进展。

    参数:
        dataset: 数据集名称，默认为 DATASET 常量。

    返回:
        日志目录的绝对路径字符串。
    """
    return str(PROJECT_ROOT / "logs" / dataset)


def variants_for_dataset(dataset: str = DATASET):
    """返回指定数据集对应的模型消融变体列表。

    当前所有数据集统一使用 MODEL_VARIANTS。历史 NYC 数据集曾使用
    固定顺序的验证变体（NYC_VERIFICATION_VARIANTS），以便复现旧的
    消融指标，现已统一化。

    参数:
        dataset: 数据集名称，默认为 DATASET 常量。

    返回:
        模型变体字典列表，每个字典包含名称、特征开关和描述。
    """
    # if dataset == "NYC":
    #     return NYC_VERIFICATION_VARIANTS
    return MODEL_VARIANTS


def training_config() -> dict:
    """返回数据预处理和训练流程的通用超参数字典。

    包含序列切分参数（seq_len）、数据过滤阈值（最小签到次数）、
    训练/验证集划分比例、以及优化器/学习率调度/早停等训练控制参数。

    返回:
        一个扁平字典，键为字符串形式的参数名，值为对应的配置值。
    """
    return {
        "seq_len": SEQ_LEN,
        "min_poi_checkins": MIN_POI_CHECKINS,
        "min_user_checkins": MIN_USER_CHECKINS,
        "train_ratio": TRAIN_RATIO,
        "val_ratio": VAL_RATIO,
        "batch_size": BATCH_SIZE,
        "lr": LR,
        "epochs": EPOCHS,
        "grad_clip": GRAD_CLIP,
        "patience": PATIENCE,
        "scheduler_factor": SCHEDULER_FACTOR,
        "scheduler_patience": SCHEDULER_PATIENCE,
        "seed": SEED,
    }


def model_config() -> dict:
    """返回 Transformer 推荐模型的结构超参数字典。

    包含嵌入维度（场地、类别、行为语义、文本语义及其投影维度）、
    Transformer 编码器配置（d_model, n_heads, n_layers, ff_dim）
    以及 Dropout 正则化参数。

    返回:
        一个扁平字典，键为字符串形式的参数名，值为对应的配置值。
    """
    return {
        "venue_emb_dim": VENUE_EMB_DIM,
        "cat_emb_dim": CAT_EMB_DIM,
        "behav_dim": BEHAV_EMB_DIM,
        "behav_proj_dim": BEHAV_PROJ_DIM,
        "text_dim": TEXT_EMB_DIM,
        "text_proj_dim": TEXT_PROJ_DIM,
        "d_model": D_MODEL,
        "n_heads": N_HEADS,
        "n_layers": N_LAYERS,
        "ff_dim": FF_DIM,
        "dropout": DROPOUT,
        "fc_dropout": FC_DROPOUT,
    }


# ==============================================================================
# SASRec 配置
# ==============================================================================

# SASRec 超参数（与当前 Transformer 对齐，以进行公平比较）
SASREC_HIDDEN_SIZE = 128  # 与 D_MODEL 一致
SASREC_N_LAYERS = 2  # 与 N_LAYERS 一致
SASREC_N_HEADS = 2  # 与 N_HEADS 一致
SASREC_INNER_SIZE = 256  # 与 FF_DIM 一致
SASREC_HIDDEN_DROPOUT = 0.2  # 略高于 Transformer 的 0.1（遵循原始 SASRec 的设置）
SASREC_ATTN_DROPOUT = 0.2
SASREC_HIDDEN_ACT = "gelu"  # 与 Transformer 一致
SASREC_LAYER_NORM_EPS = 1e-12
SASREC_INITIALIZER_RANGE = 0.02

# SASRec 消融变体
SASREC_VARIANTS = [
    {
        "name": "SASRec_Baseline",
        "use_behav": False,
        "shuffle_behav": False,
        "description": "SASRec + 仅 POI ID 和位置嵌入",
    },
    {
        "name": "SASRec_Behavioral",
        "use_behav": True,
        "shuffle_behav": False,
        "description": "SASRec + 行为语义嵌入（拼接 + 线性融合）",
    },
    {
        "name": "SASRec_Behavioral_Shuffle",
        "use_behav": True,
        "shuffle_behav": True,
        "description": "SASRec + 打乱的行为语义嵌入（容量控制）",
    },
]

# SASRec 报告顺序
SASREC_REPORT_ORDER = [
    "SASRec_Baseline",
    "SASRec_Behavioral",
    "SASRec_Behavioral_Shuffle",
]


def sasrec_config() -> dict:
    """返回 SASRec 模型专用的超参数配置。"""
    return {
        "hidden_size": SASREC_HIDDEN_SIZE,
        "max_seq_len": SEQ_LEN,  # 使用与 Transformer 相同的序列长度
        "n_layers": SASREC_N_LAYERS,
        "n_heads": SASREC_N_HEADS,
        "inner_size": SASREC_INNER_SIZE,
        "hidden_dropout_prob": SASREC_HIDDEN_DROPOUT,
        "attn_dropout_prob": SASREC_ATTN_DROPOUT,
        "hidden_act": SASREC_HIDDEN_ACT,
        "layer_norm_eps": SASREC_LAYER_NORM_EPS,
        "initializer_range": SASREC_INITIALIZER_RANGE,
        "behav_dim": BEHAV_EMB_DIM,
        "behav_proj_dim": BEHAV_PROJ_DIM,
    }


def sasrec_variants(dataset: str = DATASET):
    """返回给定数据集的 SASRec 消融变体列表。"""
    return SASREC_VARIANTS


# ==============================================================================
# 时间编码消融实验配置
# ==============================================================================

# 时间编码：将 4 维 sin-cos 特征投影到一个小的嵌入空间
TIME_EMB_DIM = 16  # 为时间信号分配较小的预算，保持对行为语义的关注

# 时间消融变体（用于核心四组比较）
TIME_VARIANTS = [
    {
        "name": "T1_Baseline",
        "use_time": False,
        "use_behav": False,
        "shuffle_behav": False,
        "description": "ID + Category（无时间，无行为语义）",
    },
    {
        "name": "T_time",
        "use_time": True,
        "use_behav": False,
        "shuffle_behav": False,
        "description": "ID + Category + 时间编码（sin-cos 小时/星期几）",
    },
    {
        "name": "T_behavioral",
        "use_time": False,
        "use_behav": True,
        "shuffle_behav": False,
        "description": "ID + Category + 行为语义嵌入",
    },
    {
        "name": "T_time_behavioral",
        "use_time": True,
        "use_behav": True,
        "shuffle_behav": False,
        "description": "ID + Category + 时间 + 行为语义（完整模型）",
    },
]

# 扩展变体（可选，当 BERT 文本特征可用时使用）
TIME_VARIANTS_EXTENDED = TIME_VARIANTS + [
    {
        "name": "T_time_bert",
        "use_time": True,
        "use_behav": False,
        "shuffle_behav": False,
        "use_text": True,
        "description": "ID + Category + 时间 + BERT 文本",
    },
    {
        "name": "T_time_behavioral_bert",
        "use_time": True,
        "use_behav": True,
        "shuffle_behav": False,
        "use_text": True,
        "description": "ID + Category + 时间 + Behavior + BERT（完全融合）",
    },
]

TIME_REPORT_ORDER = [
    "T1_Baseline",
    "T_time",
    "T_behavioral",
    "T_time_behavioral",
]


def time_variants(dataset: str = DATASET):
    """返回给定数据集的时间消融变体列表。"""
    return TIME_VARIANTS
