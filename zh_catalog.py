"""Free offline Chinese search aliases and curated descriptions for Stardew Mod Hub v0.3."""

# English title matching is case-insensitive. More specific entries should precede broad ones.
KNOWN_MODS = {
    'tractor mod': ('拖拉机 MOD', '添加可驾驶的拖拉机，辅助耕地、播种等农场作业。', '自动化'),
    'automate': ('自动化 MOD', '让箱子与附近的加工设备自动协作，减少重复操作。', '自动化'),
    'generic mod config menu': ('通用 MOD 配置菜单', '在游戏内调整支持该功能的 MOD 配置。', '工具'),
    'npc map locations': ('NPC 地图位置', '在地图上显示村民的位置。', '地图'),
    'lookup anything': ('万物查询', '查询游戏物品、角色等信息。', '工具'),
    'chests anywhere': ('随处访问箱子', '从不同地点访问箱子和存储内容。', '便利'),
    'better ranching': ('更好的牧场管理', '为牧场动物照料提供提示。', '便利'),
    'skull cavern elevator': ('骷髅洞穴电梯', '为骷髅洞穴添加电梯功能。', '便利'),
    'content patcher': ('内容补丁框架', '为内容包提供数据修改框架。', '框架'),
    'stardew valley expanded': ('星露谷物语扩展', '大型剧情、地图和人物内容扩展。', '扩展'),
    '[cp] mountain map replica': (
        '[CP] 山区地图复制机',
        '添加一台山区地图复制机和一个山区地图装饰品。复制机每个游戏日会产出一件物品，可能是山区采集物、采石场战利品或鱼。可在罗宾的木匠店购买。',
        '自动化',
    ),
    '[cp] desert pillar replica': (
        '[CP] 沙漠石柱复制机',
        '添加一台沙漠石柱复制机和一个装饰品。复制机每个游戏日会产出一件沙漠物品。可在绿洲商店购买。',
        '自动化',
    ),
}

# Chinese query -> English terms to search in original titles/summaries.
# Only curated aliases; not a machine translation system.
SEARCH_ALIASES = {
    '拖拉机': ['tractor'],
    '自动化': ['automate', 'automation', 'automatic', 'tractor'],
    '自动': ['automate', 'automation', 'automatic'],
    '箱子': ['chest', 'storage'],
    '物品查询': ['lookup anything'],
    '查询': ['lookup', 'search'],
    '拖拉机mod': ['tractor'],
    '背包': ['backpack', 'inventory'],
    '地图': ['map', 'location'],
    '村民': ['npc', 'villager'],
    '人物': ['npc', 'character'],
    '钓鱼': ['fish', 'fishing'],
    '农场': ['farm', 'farming'],
    '作物': ['crop', 'harvest'],
    '种植': ['plant', 'crop'],
    '动物': ['animal', 'ranch'],
    '牧场': ['ranch', 'animal'],
    '美化': ['retexture', 'visual', 'aesthetic'],
    '外观': ['retexture', 'appearance', 'portrait'],
    '头像': ['portrait'],
    '家具': ['furniture'],
    '服装': ['clothes', 'fashion', 'outfit'],
    '剧情': ['story', 'event', 'dialogue'],
    '扩展': ['expanded', 'expansion'],
    '汉化': ['chinese', 'translation', 'localization'],
    '中文': ['chinese', 'translation', 'localization'],
    '配置': ['config', 'settings'],
    '工具': ['tool', 'utility'],
    '电梯': ['elevator'],
    '矿洞': ['mine', 'cavern'],
}

CATEGORY_RULES = [
    ('框架', ['content patcher', 'framework', 'api', 'smapi']),
    ('自动化', ['tractor', 'automate', 'automation', 'automatic', 'machine']),
    ('地图', ['map', 'location', 'minimap']),
    ('外观', ['retexture', 'portrait', 'furniture', 'appearance', 'aesthetic', 'clothes']),
    ('扩展', ['expanded', 'expansion', 'story', 'dialogue', 'new npc']),
    ('便利', ['chest', 'inventory', 'quality of life', 'elevator']),
    ('工具', ['config', 'settings', 'lookup', 'utility']),
]


def enrich(title, summary=''):
    """Return (Chinese title, Chinese summary, category); unknown entries stay untranslated."""
    lower_title = str(title or '').casefold().strip()
    # Exact names avoid translating unrelated mods that happen to contain a keyword.
    if lower_title in KNOWN_MODS:
        return KNOWN_MODS[lower_title]
    text = (str(title or '') + ' ' + str(summary or '')).casefold()
    for category, words in CATEGORY_RULES:
        if any(word in text for word in words):
            return '', '', category
    return '', '', '其他'


def query_terms(q):
    """Expand Chinese keywords into English search terms without paid APIs."""
    q = str(q or '').strip()
    terms = [q] if q else []
    for chinese, english_terms in SEARCH_ALIASES.items():
        if chinese in q:
            terms.extend(english_terms)
    # Deduplicate while preserving order, avoid runaway queries.
    return list(dict.fromkeys(t for t in terms if t))[:20]
