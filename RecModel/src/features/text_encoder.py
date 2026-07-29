"""
Sentence-BERT 文本语义编码，用于 POI 描述。

使用预训练的 all-MiniLM-L6-v2 模型对每个 POI 的文本描述进行编码
（模板格式：类别 + 地理区域）。
"""
import numpy as np
import logging
from typing import Dict, List

logger = logging.getLogger(__name__)


# 基于经纬度坐标的 NYC 街区/区域划分
# 逻辑：用纬线和经线将 NYC 划分成不重叠的矩形区域，从上到下、从东到西依次判定
def get_nyc_zone(lat: float, lon: float) -> str:
    """将 GPS 坐标映射到人类可读的 NYC 街区名称。"""
    if lat >= 40.75 and lon >= -73.98:
        return "Upper East Side Manhattan"
    if lat >= 40.75:
        return "Upper West Side Manhattan"
    if lat >= 40.72 and lon >= -73.98:
        return "Midtown East Manhattan"
    if lat >= 40.72:
        return "Midtown West Manhattan"
    if lat >= 40.68 and lon >= -73.98:
        return "East Village Manhattan"
    if lat >= 40.68:
        return "Greenwich Village Manhattan"
    if lat >= 40.62 and lon <= -73.95:
        return "Brooklyn"
    if lat >= 40.62:
        return "Lower East Side Manhattan"
    if lon <= -73.90:
        return "Queens"
    return "NYC Metropolitan Area"


def get_tky_zone(lat: float, lon: float) -> str:
    """将 GPS 坐标映射到粗略的 Tokyo 区域标签。

    同样是按纬线划分南北、经线划分东西的规则判定法，区域命名对应东京的主要
    商圈和生活区（如池袋、新宿、涩谷、银座等），让后续文本描述带有位置语义。
    """
    if lat >= 35.72 and lon < 139.75:
        return "Ikebukuro and North Tokyo"
    if lat >= 35.72:
        return "Ueno and Asakusa Tokyo"
    if lat >= 35.68 and lon < 139.72:
        return "Shinjuku and West Tokyo"
    if lat >= 35.68:
        return "Chiyoda and Central Tokyo"
    if lat >= 35.64 and lon < 139.72:
        return "Shibuya and Meguro Tokyo"
    if lat >= 35.64:
        return "Ginza and Tokyo Bay"
    if lon < 139.70:
        return "Southwest Tokyo"
    if lon >= 139.80:
        return "Tokyo Bay Area"
    return "Tokyo Metropolitan Area"


def get_zone(lat: float, lon: float, dataset: str) -> str:
    """根据数据集选择对应的地理区域文本标签。

    统一的入口函数：根据 dataset 标识（"TKY" 或其他）自动路由到对应城市的地理
    区域映射函数，使得上层调用者无需关心使用的是哪个数据集的坐标体系。
    """
    if dataset == "TKY":
        return get_tky_zone(lat, lon)
    return get_nyc_zone(lat, lon)


def build_poi_texts(
    venue_ids: List[str],
    venue_to_category: Dict[str, str],
    venue_to_location: Dict[str, Dict[str, float]],
    dataset: str = "NYC",
) -> Dict[str, str]:
    """
    为每个 POI 构建自然语言描述。

    模板："【类别】位于【数据集对应的地理区域】"

    设计意图：将结构化的 POI 元数据（类别 + GPS 坐标）转换成自然语言句子。
    这种"模板填充"生成的人造语料虽然简单，但足以让 Sentence-BERT 捕捉到
    "同类别的 POI"和"同区域的 POI"之间的语义相似性，从而产生有意义的文本嵌入。

    Args:
        venue_ids: 唯一 POI ID 列表
        venue_to_category: POI ID → 类别字符串
        venue_to_location: POI ID → {'latitude': float, 'longitude': float}

    Returns:
        POI ID → 文本描述字符串
    """
    # 遍历每个 POI：取类别名称 + GPS 坐标 → 查地理区域 → 拼成描述句子
    texts = {}
    for vid in venue_ids:
        cat = venue_to_category.get(vid, "Place")
        loc = venue_to_location.get(vid, {})
        # 坐标缺失时使用数据集的城市中心位置作为兜底
        lat = loc.get('latitude', 35.68 if dataset == "TKY" else 40.7)
        lon = loc.get('longitude', 139.76 if dataset == "TKY" else -74.0)
        zone = get_zone(lat, lon, dataset)
        texts[vid] = f"{cat} located in {zone}"  # 英文模板："{类别} located in {区域}"

    logger.info(f"  Built text descriptions for {len(texts)} POIs")
    logger.info(f"  Example: [{venue_to_category.get(venue_ids[0], '?')}] "
                f"→ \"{texts[venue_ids[0]]}\"")
    return texts


def encode_with_sbert(
    poi_texts: Dict[str, str],
    model_name: str = 'all-MiniLM-L6-v2',
    batch_size: int = 256,
    local_files_only: bool = False,
) -> Dict[str, np.ndarray]:
    """
    使用 Sentence-BERT 对 POI 文本描述进行编码。

    流程概述：
    1. 加载预训练的 Sentence-BERT 模型（默认 all-MiniLM-L6-v2）
    2. 批量编码所有 POI 描述文本
    3. L2 归一化所有嵌入向量，以便后续用余弦相似度检索
    4. 显式释放模型并清空 GPU 缓存，因为编码是一次性操作，完成后不需要模型常驻

    Args:
        poi_texts: POI ID → 文本描述
        model_name: HuggingFace 模型标识符
        batch_size: 编码批次大小
        local_files_only: 是否仅从本地 HuggingFace 缓存加载模型

    Returns:
        POI ID → L2 归一化的 384 维嵌入向量
    """
    from sentence_transformers import SentenceTransformer

    logger.info(f"  Loading Sentence-BERT: {model_name}")
    model = SentenceTransformer(model_name, local_files_only=local_files_only)
    logger.info(f"  Embedding dimension: {model.get_sentence_embedding_dimension()}")

    vid_list = list(poi_texts.keys())
    text_list = [poi_texts[vid] for vid in vid_list]

    logger.info(f"  Encoding {len(text_list)} texts...")
    # 调用 SBERT 编码器，将文本列表批量转为固定维度（384 维）的向量
    vectors = model.encode(text_list, show_progress_bar=True, batch_size=batch_size)

    # L2 归一化：将所有向量长度缩放到 1，投影到单位超球面，
    # 确保余弦相似度 = 内积，消除向量模长的影响
    vectors = vectors / (np.linalg.norm(vectors, axis=1, keepdims=True) + 1e-8)

    result = {vid: vectors[i].astype(np.float32) for i, vid in enumerate(vid_list)}
    logger.info(f"  Encoded {len(result)} POI embeddings, shape=({vectors.shape[1]},)")

    # 显式释放 SBERT 模型以释放 GPU 显存
    # 编码是一次性操作（不需要在线推理），完成后立即删除模型对象并清空 CUDA 缓存，
    # 为后续的模型训练或数据处理腾出宝贵的 GPU 内存空间
    del model
    import torch
    if torch.cuda.is_available():
        torch.cuda.empty_cache()

    return result


def build_text_matrix(
    text_embeddings: Dict[str, np.ndarray],
    venue_to_idx: Dict[str, int],
) -> np.ndarray:
    """
    将文本嵌入对齐到模型的 POI 词表。

    与 Word2Vec 的 build_behavioral_matrix 功能对称：将字典形式的编码结果
    （POI ID → 向量）重新排列成一个按 venue_to_idx 索引的稠密矩阵。
    在模型词表中出现但缺少文本嵌入的 POI 将保持为零向量。

    Args:
        text_embeddings: POI ID → 嵌入向量
        venue_to_idx: 模型的 POI → 索引映射

    Returns:
        (num_venues, emb_dim) 形状的对齐嵌入矩阵
    """
    num_venues = len(venue_to_idx)
    emb_dim = next(iter(text_embeddings.values())).shape[0]
    matrix = np.zeros((num_venues, emb_dim), dtype=np.float32)
    count = 0

    for vid, idx in venue_to_idx.items():
        if vid != '<PAD>' and vid in text_embeddings:
            matrix[idx] = text_embeddings[vid]
            count += 1

    logger.info(f"  Text matrix: {matrix.shape}, coverage={count}/{num_venues - 1}")
    return matrix
