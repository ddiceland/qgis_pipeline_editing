# -*- coding: utf-8 -*-
"""把结构名称收成配置内部编号：汉字转拼音，英文直接用。"""

import re

# 末尾套话，转编号时去掉，避免「秦华结构」变成 qinhuajiegou
_CN_SUFFIXES = ("结构组", "结构", "数据库", "库", "组")
_EN_SUFFIXES = ("structure", "group", "library", "schema")

# 多音字取更常见的地名/机构读音（西=xi、行=xing）
_PINYIN_GROUPS = (
    ("a", "啊阿"),
    ("ai", "爱哀矮艾碍埃"),
    ("an", "安按暗岸案"),
    ("ang", "昂"),
    ("ao", "奥澳傲"),
    ("ba", "把八巴罢爸霸坝"),
    ("bai", "百白柏败拜"),
    ("ban", "办半板班般版"),
    ("bang", "帮邦榜棒"),
    ("bao", "报保包宝抱暴薄"),
    ("bei", "北被备背倍贝"),
    ("ben", "本"),
    ("beng", "崩泵"),
    ("bi", "比必笔毕避闭壁碧"),
    ("bian", "变边便编遍"),
    ("biao", "表标"),
    ("bie", "别"),
    ("bin", "宾滨彬"),
    ("bing", "并病兵冰"),
    ("bo", "波博播伯"),
    ("bu", "不部步布补"),
    ("ca", "擦"),
    ("cai", "才采材财彩菜蔡"),
    ("can", "参残"),
    ("cang", "仓苍藏"),
    ("cao", "草操曹"),
    ("ce", "测策侧册"),
    ("ceng", "层曾"),
    ("cha", "查差插察"),
    ("chai", "拆柴"),
    ("chan", "产单阐"),
    ("chang", "长常场厂昌畅唱"),
    ("chao", "朝超潮抄"),
    ("che", "车彻撤"),
    ("chen", "陈沉晨称臣"),
    ("cheng", "成城程承呈乘澄"),
    ("chi", "持吃池迟尺赤"),
    ("chong", "重冲充崇"),
    ("chou", "抽仇筹丑"),
    ("chu", "出处初除楚础储"),
    ("chuan", "传川船穿串"),
    ("chuang", "创窗床"),
    ("chui", "吹垂锤"),
    ("chun", "春纯"),
    ("chuo", "绰"),
    ("ci", "此次词辞磁"),
    ("cong", "从丛聪"),
    ("cou", "凑"),
    ("cu", "促粗"),
    ("cuan", "窜"),
    ("cui", "催翠"),
    ("cun", "村存"),
    ("cuo", "错措"),
    ("da", "大打达答"),
    ("dai", "代带待戴袋"),
    ("dan", "但单担丹淡石"),
    ("dang", "当党档荡"),
    ("dao", "到道导岛倒刀"),
    ("de", "的得德"),
    ("deng", "等登灯邓"),
    ("di", "地第低底帝抵滴"),
    ("dian", "点电典店淀殿"),
    ("diao", "调掉雕"),
    ("die", "跌叠"),
    ("ding", "定丁顶订"),
    ("dong", "东动懂冬洞董"),
    ("dou", "都斗豆"),
    ("du", "度独读杜督渡"),
    ("duan", "段断短端"),
    ("dui", "对队堆"),
    ("dun", "盾顿"),
    ("duo", "多夺"),
    ("e", "额恶俄"),
    ("en", "恩"),
    ("er", "而二尔儿"),
    ("fa", "发法"),
    ("fan", "反范翻凡繁饭樊"),
    ("fang", "方放房防仿芳"),
    ("fei", "非飞费废肥"),
    ("fen", "分份纷奋"),
    ("feng", "风封丰冯峰凤"),
    ("fo", "佛"),
    ("fou", "否"),
    ("fu", "服复府父负福副富傅符"),
    ("ga", "嘎"),
    ("gai", "改该概盖"),
    ("gan", "干感甘敢赶杆"),
    ("gang", "刚钢港岗"),
    ("gao", "高告稿"),
    ("ge", "个各格歌革隔葛"),
    ("gei", "给"),
    ("gen", "根跟"),
    ("geng", "更耕"),
    ("gong", "工公共功供宫龚"),
    ("gou", "构沟够购勾"),
    ("gu", "古故固顾谷骨鼓"),
    ("gua", "挂瓜"),
    ("guai", "怪拐"),
    ("guan", "关管观官馆惯冠"),
    ("guang", "光广"),
    ("gui", "规贵归轨桂"),
    ("gun", "滚"),
    ("guo", "国过果郭"),
    ("ha", "哈"),
    ("hai", "还海害孩亥"),
    ("han", "汉含寒韩喊汗邯"),
    ("hang", "航杭"),
    ("hao", "好号毫豪郝"),
    ("he", "和合河何核贺赫"),
    ("hei", "黑"),
    ("hen", "很恨"),
    ("heng", "横衡恒"),
    ("hong", "红洪宏鸿"),
    ("hou", "后候厚侯"),
    ("hu", "护户湖互胡虎沪"),
    ("hua", "化华花画话滑桦"),
    ("huai", "怀坏淮"),
    ("huan", "环换还欢缓"),
    ("huang", "黄皇荒煌"),
    ("hui", "会回挥灰惠辉"),
    ("hun", "混婚"),
    ("huo", "活或火货获"),
    ("ji", "机及级计己基集际技济极纪季冀"),
    ("jia", "家加价甲架嘉贾"),
    ("jian", "建间件见简坚减检健剑"),
    ("jiang", "将江讲降蒋姜"),
    ("jiao", "教交较叫角焦胶"),
    ("jie", "界解接结阶介街杰"),
    ("jin", "进金今近尽紧津锦"),
    ("jing", "经精京静景井警净晶"),
    ("jiong", "炯"),
    ("jiu", "就九旧久酒救"),
    ("ju", "具据局举居聚剧"),
    ("juan", "卷捐"),
    ("jue", "决觉绝"),
    ("jun", "军均君俊"),
    ("ka", "卡"),
    ("kai", "开凯"),
    ("kan", "看刊坎"),
    ("kang", "康抗"),
    ("kao", "考靠"),
    ("ke", "可科客克课柯"),
    ("ken", "肯垦"),
    ("keng", "坑"),
    ("kong", "空控孔"),
    ("kou", "口扣"),
    ("ku", "苦库酷"),
    ("kua", "跨夸"),
    ("kuai", "快块"),
    ("kuan", "宽款"),
    ("kuang", "况矿旷"),
    ("kui", "亏奎"),
    ("kun", "困昆"),
    ("kuo", "扩括阔"),
    ("la", "拉啦落"),
    ("lai", "来莱赖"),
    ("lan", "兰蓝栏览澜"),
    ("lang", "浪朗郎廊"),
    ("lao", "老劳捞"),
    ("le", "了乐勒"),
    ("lei", "类雷累磊"),
    ("leng", "冷"),
    ("li", "理力立利里李历丽黎礼沥"),
    ("lian", "连联练脸链莲"),
    ("liang", "两量良亮梁"),
    ("liao", "了料疗辽廖"),
    ("lie", "列烈裂"),
    ("lin", "林临邻淋麟"),
    ("ling", "领另令灵零陵"),
    ("liu", "流六留刘柳"),
    ("long", "龙隆"),
    ("lou", "楼露娄"),
    ("lu", "路陆录鲁卢炉鹿"),
    ("lv", "律率绿旅吕铝"),
    ("luan", "乱滦"),
    ("lue", "略"),
    ("lun", "论轮伦"),
    ("luo", "落罗洛络"),
    ("ma", "马吗妈麻玛"),
    ("mai", "买卖麦迈"),
    ("man", "满慢漫曼"),
    ("mang", "忙芒"),
    ("mao", "毛冒贸茂矛"),
    ("me", "么"),
    ("mei", "没美每煤梅"),
    ("men", "们门"),
    ("meng", "蒙盟梦猛"),
    ("mi", "米密迷秘"),
    ("mian", "面免棉"),
    ("miao", "苗描秒"),
    ("mie", "灭"),
    ("min", "民敏闽"),
    ("ming", "明名命铭"),
    ("miu", "谬"),
    ("mo", "模莫末默摸"),
    ("mou", "某谋"),
    ("mu", "目母木亩穆"),
    ("na", "那南拿纳娜"),
    ("nai", "奶耐乃"),
    ("nan", "南男难"),
    ("nang", "囊"),
    ("nao", "脑闹"),
    ("ne", "呢"),
    ("nei", "内"),
    ("nen", "嫩"),
    ("neng", "能"),
    ("ni", "你尼泥逆"),
    ("nian", "年念"),
    ("niang", "娘"),
    ("niao", "鸟"),
    ("nie", "聂镍"),
    ("nin", "您"),
    ("ning", "宁凝"),
    ("niu", "牛纽"),
    ("nong", "农浓弄"),
    ("nu", "努怒"),
    ("nv", "女"),
    ("nuan", "暖"),
    ("nue", "虐"),
    ("nuo", "诺挪"),
    ("ou", "区欧偶"),
    ("pa", "怕爬帕"),
    ("pai", "派排牌拍"),
    ("pan", "判盘潘攀"),
    ("pang", "旁庞"),
    ("pao", "跑炮泡"),
    ("pei", "配培佩"),
    ("pen", "喷盆"),
    ("peng", "朋鹏彭蓬"),
    ("pi", "批皮辟匹"),
    ("pian", "片偏"),
    ("piao", "票飘"),
    ("pie", "撇"),
    ("pin", "品贫频"),
    ("ping", "平评凭萍"),
    ("po", "破坡颇"),
    ("pou", "剖"),
    ("pu", "普铺浦朴"),
    ("qi", "起其气期器企七齐奇棋启戚"),
    ("qia", "恰卡"),
    ("qian", "前千钱签潜迁乾"),
    ("qiang", "强抢墙枪"),
    ("qiao", "桥巧乔悄"),
    ("qie", "切且"),
    ("qin", "亲勤秦琴侵沁"),
    ("qing", "情青清请庆轻晴"),
    ("qiong", "穷琼"),
    ("qiu", "求秋球丘"),
    ("qu", "去区取曲趋渠"),
    ("quan", "全权泉圈"),
    ("que", "却确缺"),
    ("qun", "群"),
    ("ran", "然染冉"),
    ("rang", "让"),
    ("rao", "绕扰"),
    ("re", "热"),
    ("ren", "人任认仁"),
    ("reng", "仍"),
    ("ri", "日"),
    ("rong", "容荣融溶蓉"),
    ("rou", "肉柔"),
    ("ru", "如入乳儒"),
    ("ruan", "软阮"),
    ("rui", "瑞锐"),
    ("run", "润"),
    ("ruo", "若弱"),
    ("sa", "萨撒"),
    ("sai", "赛塞"),
    ("san", "三散"),
    ("sang", "桑丧"),
    ("sao", "扫骚"),
    ("se", "色"),
    ("sen", "森"),
    ("seng", "僧"),
    ("sha", "沙杀砂厦"),
    ("shai", "晒筛"),
    ("shan", "山善单闪陕杉汕"),
    ("shang", "上商尚伤"),
    ("shao", "少绍烧邵"),
    ("she", "社设射涉舍"),
    ("shen", "深神身什审申沈"),
    ("sheng", "生省声升盛圣"),
    ("shi", "是时实事十使世市识始石师史施"),
    ("shou", "手受收首守寿"),
    ("shu", "数书术属树输束署舒"),
    ("shua", "刷耍"),
    ("shuai", "帅衰摔"),
    ("shuan", "栓"),
    ("shuang", "双爽"),
    ("shui", "水税谁"),
    ("shun", "顺"),
    ("shuo", "说硕"),
    ("si", "司四思斯似死私寺"),
    ("song", "送松宋"),
    ("sou", "搜"),
    ("su", "速素苏诉塑宿"),
    ("suan", "算酸"),
    ("sui", "随岁虽碎"),
    ("sun", "孙损"),
    ("suo", "所索缩锁"),
    ("ta", "他它她塔踏"),
    ("tai", "太台态泰抬"),
    ("tan", "谈弹探坦炭潭谭"),
    ("tang", "堂唐糖汤塘"),
    ("tao", "套讨陶逃桃"),
    ("te", "特"),
    ("teng", "腾藤"),
    ("ti", "体提题替梯"),
    ("tian", "天田添填"),
    ("tiao", "条调跳"),
    ("tie", "铁贴"),
    ("ting", "听停庭厅挺"),
    ("tong", "同通统童铜桐"),
    ("tou", "头投透"),
    ("tu", "土图突途涂"),
    ("tuan", "团"),
    ("tui", "推退"),
    ("tun", "屯吞"),
    ("tuo", "脱托拓拖"),
    ("wa", "瓦挖娃"),
    ("wai", "外"),
    ("wan", "万完晚湾玩宛"),
    ("wang", "王望往网忘汪"),
    ("wei", "为位未委维威微卫魏"),
    ("wen", "文问温稳闻"),
    ("weng", "翁"),
    ("wo", "我握沃"),
    ("wu", "务物无五武吴午误伍巫"),
    ("xi", "系西席息习洗喜细希溪锡"),
    ("xia", "下夏峡厦"),
    ("xian", "现先线县限显险献咸"),
    ("xiang", "想向相象香乡祥详项"),
    ("xiao", "小效消校晓肖萧"),
    ("xie", "些写协谢械鞋解"),
    ("xin", "新心信辛欣鑫"),
    ("xing", "行性形型兴星邢"),
    ("xiong", "雄兄熊"),
    ("xiu", "修秀休"),
    ("xu", "需许续须序徐蓄"),
    ("xuan", "选宣玄旋"),
    ("xue", "学雪血薛"),
    ("xun", "训讯迅寻巡循"),
    ("ya", "压牙亚雅崖"),
    ("yan", "眼言研严延演沿颜燕阎"),
    ("yang", "样阳杨洋央养羊"),
    ("yao", "要药摇腰姚耀"),
    ("ye", "业也页野夜液叶"),
    ("yi", "一以已意义议易医艺依伊宜"),
    ("yin", "因音引银印阴饮殷"),
    ("ying", "应影英营迎硬盈"),
    ("yo", "哟"),
    ("yong", "用永勇拥涌"),
    ("you", "有由又优油游右尤"),
    ("yu", "于与语育余雨预域玉渔宇俞"),
    ("yuan", "元原员院远源园袁苑"),
    ("yue", "月约越乐岳粤"),
    ("yun", "运云允匀蕴"),
    ("za", "杂砸"),
    ("zai", "在再载灾"),
    ("zan", "赞暂"),
    ("zang", "脏藏"),
    ("zao", "造早遭糟"),
    ("ze", "则责泽"),
    ("zei", "贼"),
    ("zen", "怎"),
    ("zeng", "增曾赠"),
    ("zha", "扎炸闸查"),
    ("zhai", "摘债寨"),
    ("zhan", "展战站占詹湛"),
    ("zhang", "张章长掌涨障"),
    ("zhao", "找照赵招兆"),
    ("zhe", "这着者折哲浙"),
    ("zhen", "真针阵镇振珍"),
    ("zheng", "正政整争征郑证"),
    ("zhi", "之只制直知指至治质支志织"),
    ("zhong", "中种重众终钟忠"),
    ("zhou", "周州洲轴"),
    ("zhu", "主住注助著朱诸筑柱"),
    ("zhua", "抓"),
    ("zhuai", "拽"),
    ("zhuan", "转专砖"),
    ("zhuang", "装状庄撞"),
    ("zhui", "追"),
    ("zhun", "准"),
    ("zhuo", "卓桌浊"),
    ("zi", "资子自字紫滋"),
    ("zong", "总宗纵综"),
    ("zou", "走邹"),
    ("zu", "组族足祖阻"),
    ("zuan", "钻"),
    ("zui", "最罪嘴"),
    ("zun", "尊遵"),
    ("zuo", "作做坐左座"),
)

_AUTO_ID_RE = re.compile(r"^(group|structure)_\d+$")
_STABLE_IDS = frozenset(("zhengyuan", "xian"))


def _build_char_map():
    mapping = {}
    for py, chars in _PINYIN_GROUPS:
        for ch in chars:
            if ch not in mapping:
                mapping[ch] = py
    return mapping


_CHAR_PINYIN = _build_char_map()


def _strip_name_suffix(text):
    text = (text or "").strip()
    changed = True
    while text and changed:
        changed = False
        for suf in _CN_SUFFIXES:
            if text.endswith(suf) and len(text) > len(suf):
                text = text[:-len(suf)].strip()
                changed = True
                break
        if changed:
            continue
        lower = text.lower()
        for suf in _EN_SUFFIXES:
            if lower.endswith(suf) and len(text) > len(suf):
                text = text[:len(text) - len(suf)].strip(" -_")
                changed = True
                break
    return text


def char_to_pinyin(ch):
    py = _CHAR_PINYIN.get(ch)
    if py:
        return py
    code = ord(ch)
    if 0x4E00 <= code <= 0x9FFF:
        return "h%x" % code
    return ""


def slug_from_label(label):
    """汉字转拼音并拼接；英文/数字保留为小写。"""
    text = _strip_name_suffix(label)
    if not text:
        return ""
    parts = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            parts.append(char_to_pinyin(ch))
        elif ch.isalnum():
            parts.append(ch.lower())
        elif ch in "-_ " and parts and not "".join(parts).endswith("_"):
            parts.append("_")
    slug = re.sub(r"_+", "_", "".join(parts)).strip("_")
    slug = re.sub(r"[^a-z0-9_]", "", slug)
    if slug and slug[0].isdigit():
        slug = "g_" + slug
    return slug[:48]


def unique_config_id(label, existing_ids, fallback="group"):
    occupied = {str(x or "").strip() for x in (existing_ids or []) if str(x or "").strip()}
    base = slug_from_label(label) or fallback
    sid = base
    idx = 2
    while sid in occupied:
        sid = "%s_%s" % (base, idx)
        idx += 1
    return sid


def is_auto_generated_id(sid):
    return bool(_AUTO_ID_RE.match(str(sid or "").strip()))


def is_stable_id(sid):
    return str(sid or "").strip() in _STABLE_IDS


def rewrite_mapping_key(key, id_map):
    text = str(key or "")
    if "__to__" in text:
        left, right = text.split("__to__", 1)
        return "%s__to__%s" % (id_map.get(left, left), id_map.get(right, right))
    return id_map.get(text, text)
