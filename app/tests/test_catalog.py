from merge_monitor.catalog import classify_repository


def test_explicit_category_wins_when_repository_spans_multiple_fields():
    rules = {"repository_categories": {"team/optimizer": {"category": "LLM", "subcategory": "提示与程序优化"}}}
    assert classify_repository("team/optimizer", {"topics": ["agent", "reinforcement-learning"]}, rules) == ("LLM", "提示与程序优化")


def test_unknown_repos_use_public_topics_and_preserve_unclassified_fallback():
    assert classify_repository("team/vision-eval", {"topics": ["vlm", "benchmark", "agents"]}, {}) == ("VLM", "多模态评测")
    assert classify_repository("team/trainer", {"description": "Reinforcement learning for agents"}, {}) == ("Agent", "训练与强化学习")
    assert classify_repository("team/unknown", {}, {}) == ("其他", "未分类")
