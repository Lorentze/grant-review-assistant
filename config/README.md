# 配置目录

当前 MVP 的格式规则在 `src/grant_review/extractors/` 中按申请书类型拆分：

- `nsfc_standard.py`：NSFC 2025/2026 通用申请书；
- `nsfc_overseas.py`：优秀青年科学基金项目（海外）；
- `generic.py`：未知格式的保守降级提取。

后续可在此目录增加：

- 期刊分组及别名配置；
- 不同基金类别的专用字段映射；
- 机构内部评分表和评语模板；
- 本地大模型或其他模型服务配置。
