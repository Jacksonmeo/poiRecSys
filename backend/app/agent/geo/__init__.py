"""地点解析（Stage 4 Step 4）。

GeoResolver 把 LLM 识别出的地点名称解析为空间包围盒（bbox），
避免 LLM 直接生成坐标。当前为内置地名词典实现；
未来可替换为真实地理编码服务（Nominatim / Google Geocoding 等），
只需保持 resolve() 接口不变。
"""
