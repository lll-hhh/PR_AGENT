"""Repository categories, with explicit choices before conservative topic rules."""

CATEGORY_TREE = {
    "Agent": ("自进化与搜索优化", "多智能体框架", "训练与强化学习", "编程与工具"),
    "LLM": ("提示与程序优化", "模型训练与推理", "评测与对齐"),
    "VLM": ("视觉语言模型", "多模态应用", "多模态评测"),
    "Medical AI": ("医学影像", "医学多模态与模型"),
    "RSI": ("自进化与搜索优化", "自动研究"),
    "其他": ("开发工具", "未分类"),
}


def classify_repository(repository: str, metadata: dict, rules: dict) -> tuple[str, str]:
    override = rules.get("repository_categories", {}).get(repository.lower())
    if override and override.get("category") in CATEGORY_TREE:
        category = override["category"]
        if override.get("subcategory") in CATEGORY_TREE[category]:
            return category, override["subcategory"]
    text = " ".join([repository, metadata.get("description") or "", *metadata.get("topics", [])]).lower()
    if any(word in text for word in ("medical", "healthcare", "medical-imaging", "biomedical", "medgemma")):
        return "Medical AI", "医学影像" if any(word in text for word in ("imaging", "radiology", "monai")) else "医学多模态与模型"
    if any(word in text for word in ("self-improv", "self-improving", "evolv", "recursive self", "automated research")):
        return "RSI", "自进化与搜索优化"
    if any(word in text for word in ("vlm", "vision-language", "multimodal", "multi-modal")):
        return "VLM", "多模态评测" if any(word in text for word in ("eval", "benchmark")) else "视觉语言模型"
    if "agent" in text:
        if any(word in text for word in ("evol", "self-improv", "search-optim")):
            return "Agent", "自进化与搜索优化"
        if any(word in text for word in ("reinforcement", "agent-training", "agent-rl")):
            return "Agent", "训练与强化学习"
        if any(word in text for word in ("coding", "code-agent", "tool-use")):
            return "Agent", "编程与工具"
        return "Agent", "多智能体框架"
    if any(word in text for word in ("llm", "language-model", "language model")):
        if any(word in text for word in ("prompt", "optim", "program")):
            return "LLM", "提示与程序优化"
        if any(word in text for word in ("eval", "benchmark", "alignment")):
            return "LLM", "评测与对齐"
        return "LLM", "模型训练与推理"
    return "其他", "开发工具" if any(word in text for word in ("developer-tool", "devtools")) else "未分类"
