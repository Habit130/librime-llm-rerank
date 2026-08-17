#!/usr/bin/env python3
"""Fixed Simplified-Chinese semantic regression benchmark (Squirrel #69).

The benchmark is deliberately synthetic and offline.  It is a quality floor
for the four first-round representations from #60, not a representation or
production-selection procedure.  Each case compares one historical 上文 with
one query in the same choice problem:

* ``positive`` means the two 上文 express the same choice intent with
  different wording and the historical selection is the query's expected
  candidate;
* ``hard_negative`` means the topic is related but the historical 上文 has a
  different intent, polarity, entity, number, seam/window condition, or user
  preference and must not form evidence for the query.

The source records below are the fixed benchmark content.  Four cases are
derived from each family (two directions for each relation), so changing a
sentence, axis, candidate, or choice problem changes the deterministic case
summary and the benchmark digest.

The model-free gate uses controlled vectors and a temporary SQLite facts root
to exercise the #59 exact oracle, thresholding, exact top-K, stable IDs and
summary calculation.  The opt-in real-model gate is implemented by
``daemon/integration_semantic_benchmark.py`` and writes only hashes, IDs and
numeric results to its report; it never writes raw benchmark text to a report.
"""

import argparse
import hashlib
import json
import math
import os
import shutil
import sqlite3
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))

from oracle import (  # noqa: E402
    FactReader,
    OracleParams,
    OracleQuery,
    compute_evidence,
)
from representations import first_round_specs  # noqa: E402


CONTRACT_ID = "AC-69-v1"
BENCHMARK_VERSION = "semantic-regression-benchmark-v1"
SCHEMA_ID = "luna_pinyin"
CATEGORY = "word"

# This is a benchmark threshold only.  It is not a production value and is
# not the #70 development-prefix calibration grid.
BENCHMARK_TAU = 0.90
BENCHMARK_K_EVIDENCE = 8
BENCHMARK_HALF_LIFE = float("inf")
BENCHMARK_SATURATION_K = 1.0

AXES = (
    "negation",
    "entity",
    "number_flip",
    "bpe_seam",
    "window_64",
    "preference_change",
)

FIXTURE_DISTRACTOR_CONTEXTS = (
    "合成天气记录显示周末可能有小雨，出门前准备雨具。",
    "图书馆下午开放借阅服务，读者可以按规则办理登记。",
    "园艺课程介绍了春季修剪和浇水的基本方法。",
    "博物馆公告说明本周末的展厅将分时段接待参观者。",
    "列车时刻表已经更新，旅客应当提前核对出发站。",
    "实验室把仪器校准结果整理成了内部测试记录。",
    "社区工作人员提醒居民分类投放生活垃圾。",
    "厨房采购清单列出了米面蔬菜和日常调味品。",
)


def _seam_context(core):
    """Keep a known ``今/天`` BPE boundary at the split seam."""
    return core + "，今天天气?"


def _window_context(core, length):
    """Place meaningful text at the end of a deterministic window fixture."""
    filler = "合成边界记录"
    value = core
    while len(value) < length:
        value = filler + value
    if len(value) > length:
        value = value[-length:]
    return value


def _family(family_id, axes, choice_problem, candidates, target,
            positive, negative, negative_selection=None):
    if len(positive) != 2 or len(negative) != 2:
        raise ValueError("every family needs two positive and two negative texts")
    return {
        "family_id": family_id,
        "axes": tuple(axes),
        "choice_problem": choice_problem,
        "candidates": tuple(candidates),
        "target": target,
        "positive": tuple(positive),
        "negative": tuple(negative),
        "negative_selection": negative_selection or target,
    }


# These are intentionally hand-authored semantic pairs.  The wording is not
# generated from private events or from model output.
FAMILY_SPECS = (
    # Negation: same topic, polarity changes in the hard-negative history.
    _family("negation-01", ("negation",), "kaiqi", ("开启", "开机"), "开启",
            ("这项功能暂时不要开启，等测试完成再说",
             "测试还没结束，先别打开这个功能"),
            ("验收通过后请开启这项功能",
             "测试完成以后就可以打开该功能")),
    _family("negation-02", ("negation",), "zhichi", ("支持", "失持"), "支持",
            ("我不支持这次改动，准备继续使用原方案",
             "这个修改我不会赞成，当前仍按旧流程处理"),
            ("我支持这次改动，准备切换到新方案",
             "这个修改已经得到赞成，接下来按新流程处理")),
    _family("negation-03", ("negation",), "baoliu", ("保留", "报留"), "保留",
            ("旧版本先不要删除，相关记录还要保留",
             "这些资料暂时不能清掉，历史记录需要留下"),
            ("旧版本已经确认无用，可以删除相关记录",
             "这些资料不必继续保存，历史记录可以清掉")),
    _family("negation-04", ("negation",), "quxiao", ("取消", "取笑"), "取消",
            ("行程有变但这次预约先不要取消",
             "虽然时间调整了，原来的预约仍然不撤掉"),
            ("行程有变所以决定取消这次预约",
             "时间无法配合，只能把原来的预约撤掉")),
    _family("negation-05", ("negation",), "qiyong", ("启用", "起用"), "启用",
            ("新开关暂时不要启用，等灰度结束再看",
             "灰度期间先别打开这个开关，观察完成后再决定"),
            ("灰度结束后请启用新开关",
             "观察完成以后可以把这个开关打开")),
    _family("negation-06", ("negation",), "tongguo", ("通过", "突破"), "通过",
            ("这份方案还没有通过验收，不能发布",
             "验收结果尚未合格，因此暂时不能上线"),
            ("这份方案已经通过验收，可以发布",
             "验收结果已经合格，现在可以正式上线")),
    _family("negation-07", ("negation",), "jieshou", ("接受", "假设"), "接受",
            ("新的条款我暂时不接受，还要继续讨论",
             "这组条件目前不能答应，需要再协商"),
            ("新的条款我可以接受，后续按约定执行",
             "这组条件已经答应下来，接下来照约定办理")),
    _family("negation-08", ("negation",), "yunxu", ("允许", "云雨"), "允许",
            ("安全策略不允许外部访问这个端口",
             "按照当前规则，外部连接不能进入这个端口"),
            ("安全策略允许外部访问这个端口",
             "按照当前规则，外部连接可以进入这个端口")),
    _family("negation-09", ("negation",), "zantie", ("暂停", "盘算"), "暂停",
            ("发现风险后先暂停任务，不要继续执行",
             "风险尚未排除，作业需要先停下来等待处理"),
            ("确认没有风险后继续任务，不要暂停执行",
             "检查已经完成，作业保持运行而不是停下来")),
    _family("negation-10", ("negation",), "guanbi", ("关闭", "光笔"), "关闭",
            ("会议结束前不要关闭这个页面",
             "讨论还在进行，页面暂时不能关掉"),
            ("会议结束后请关闭这个页面",
             "讨论已经结束，页面现在可以关掉")),

    # Entity: related actions, but the named entity changes.
    _family("entity-01", ("entity",), "beijing", ("北京", "背景"), "北京",
            ("下周要去北京参加技术展会",
             "计划到北京出差，顺便参观行业展览"),
            ("下周要去上海参加技术展会",
             "计划到上海出差，顺便参观行业展览")),
    _family("entity-02", ("entity",), "shanghai", ("上海", "商海"), "上海",
            ("客户会议安排在上海举行",
             "这次要到上海和客户当面开会"),
            ("客户会议安排在杭州举行",
             "这次要到杭州和客户当面开会")),
    _family("entity-03", ("entity",), "guangzhou", ("广州", "光州"), "广州",
            ("公司的华南仓库设在广州",
             "华南物流中心的位置定在广州"),
            ("公司的华南仓库设在深圳",
             "华南物流中心的位置定在深圳")),
    _family("entity-04", ("entity",), "shenzhen", ("深圳", "深镇"), "深圳",
            ("深圳团队负责这次产品发布",
             "这次发布由深圳的项目组负责"),
            ("东莞团队负责这次产品发布",
             "这次发布由东莞的项目组负责")),
    _family("entity-05", ("entity",), "hangzhou", ("杭州", "航州"), "杭州",
            ("暑假准备去杭州游览西湖",
             "假期计划到杭州旅行，重点看看西湖"),
            ("暑假准备去苏州游览园林",
             "假期计划到苏州旅行，重点看看园林")),
    _family("entity-06", ("entity",), "nanjing", ("南京", "难经"), "南京",
            ("南京校区下个月开始招生",
             "下月先由南京的校区启动新生报名"),
            ("合肥校区下个月开始招生",
             "下月先由合肥的校区启动新生报名")),
    _family("entity-07", ("entity",), "wuhan", ("武汉", "无汗"), "武汉",
            ("武汉的研发中心正在招聘工程师",
             "研发岗位主要由武汉中心负责招聘"),
            ("长沙的研发中心正在招聘工程师",
             "研发岗位主要由长沙中心负责招聘")),
    _family("entity-08", ("entity",), "chengdu", ("成都", "成读"), "成都",
            ("成都站是这趟列车的终点",
             "这趟车最后会抵达成都车站"),
            ("重庆站是这趟列车的终点",
             "这趟车最后会抵达重庆车站")),

    # Number flip: equivalent wording is positive; a changed number is not.
    _family("number-01", ("number_flip",), "sandiandian", ("三点", "散点"), "三点",
            ("会议安排在周三下午三点开始",
             "周三的会定在下午十五时开场"),
            ("会议安排在周三下午四点开始",
             "周三的会定在下午十六时开场")),
    _family("number-02", ("number_flip",), "santian", ("三天", "散天"), "三天",
            ("这个修复预计三天内完成",
             "这项修复大约需要七十二小时"),
            ("这个修复预计五天内完成",
             "这项修复大约需要一百二十小时")),
    _family("number-03", ("number_flip",), "ershi", ("二十", "儿时"), "二十",
            ("请把样本数量设为二十份",
             "样本数按二十份准备就可以了"),
            ("请把样本数量设为三十份",
             "样本数按三十份准备就可以了")),
    _family("number-04", ("number_flip",), "liangbai", ("两百", "量百"), "两百",
            ("这批物料先采购两百件",
             "第一批准备购买二百个单位"),
            ("这批物料先采购三百件",
             "第一批准备购买三百个单位")),
    _family("number-05", ("number_flip",), "diyi", ("第一", "低意"), "第一",
            ("请优先处理第一项风险",
             "风险列表中的首项要先解决"),
            ("请优先处理第二项风险",
             "风险列表中的第二项要先解决")),
    _family("number-06", ("number_flip",), "nianfen", ("二〇二六", "二〇二七"), "二〇二六",
            ("合同有效期到二〇二六年年底",
             "这份合同会持续到2026年末"),
            ("合同有效期到二〇二七年年底",
             "这份合同会持续到2027年末")),
    _family("number-07", ("number_flip",), "shierlou", ("十二楼", "十三楼"), "十二楼",
            ("培训地点在办公楼十二楼",
             "请到大楼的第十二层参加培训"),
            ("培训地点在办公楼十三楼",
             "请到大楼的第十三层参加培训")),
    _family("number-08", ("number_flip",), "wuxiang", ("五项", "无项"), "五项",
            ("清单里一共需要填写五项内容",
             "表格总共列出五个需要填写的栏目"),
            ("清单里一共需要填写两项内容",
             "表格总共列出两个需要填写的栏目")),

    # BPE seam: the final ``今天天气?`` keeps the known 今/天 seam probe.
    _family("bpe-01", ("bpe_seam",), "shangxian", ("上线", "上限"), "上线",
            (_seam_context("代码评审已经完成，版本准备在本周发布"),
             _seam_context("评审通过以后，这个版本就可以部署到线上")),
            (_seam_context("代码评审已经完成，版本的容量上限需要重新测量"),
             _seam_context("评审通过以后，先检查系统能够承受的最大负载"))),
    _family("bpe-02", ("bpe_seam",), "shuju", ("数据", "属具"), "数据",
            (_seam_context("实验结果已经收集完毕，接下来整理数据"),
             _seam_context("测量记录全部归档，现在开始汇总样本信息")),
            (_seam_context("实验设备已经收集完毕，接下来整理仪器"),
             _seam_context("测量工具全部归档，现在开始清点实验器材"))),
    _family("bpe-03", ("bpe_seam",), "jishu", ("技术", "急速"), "技术",
            (_seam_context("研发团队正在讨论新的技术路线"),
             _seam_context("工程师准备评估下一代实现方案")),
            (_seam_context("研发团队正在讨论如何加快处理速度"),
             _seam_context("工程师准备评估一次快速执行的方案"))),
    _family("bpe-04", ("bpe_seam",), "chengxu", ("程序", "成序"), "程序",
            (_seam_context("安装包下载完成后请运行程序进行检查"),
             _seam_context("文件装好以后打开应用，确认软件能够启动")),
            (_seam_context("安装包下载完成后请排列程序步骤"),
             _seam_context("文件装好以后先安排流程，确认顺序能够执行"))),
    _family("bpe-05", ("bpe_seam",), "gongcheng", ("工程", "公称"), "工程",
            (_seam_context("桥梁施工进入最后阶段，工程进度需要复核"),
             _seam_context("建筑项目接近完工，现在核对施工进展")),
            (_seam_context("产品铭牌上的公称尺寸需要复核"),
             _seam_context("设备标注的标准尺寸需要重新确认"))),
    _family("bpe-06", ("bpe_seam",), "xiangmu", ("项目", "相目"), "项目",
            (_seam_context("项目计划已经批准，团队下周开始实施"),
             _seam_context("方案获得确认后，工作组准备进入执行阶段")),
            (_seam_context("目录里的相貌条目已经整理，团队下周开始校对"),
             _seam_context("人物的外貌资料获得确认，工作组准备进入核对阶段"))),
    _family("bpe-07", ("bpe_seam",), "huodong", ("活动", "活东"), "活动",
            (_seam_context("周末社区要举办亲子活动，报名名单正在确认"),
             _seam_context("社区将在周末安排家庭互动，参加人员需要登记")),
            (_seam_context("设备运行时出现活动部件，维修人员正在确认"),
             _seam_context("机器内部有一个运动零件，技术人员需要登记"))),
    _family("bpe-08", ("bpe_seam",), "jianyi", ("建议", "见义"), "建议",
            (_seam_context("评审结束后请提出建议，帮助我们改进方案"),
             _seam_context("看完材料以后欢迎给出意见，方便下一轮修订")),
            (_seam_context("遇到危险时应当见义勇为，及时帮助他人"),
             _seam_context("公共场所发生意外时可以挺身而出，协助受困者"))),

    # Window boundary: query is exactly 64 characters; history is longer than
    # 64 so the representation must use the defined tail window.
    _family("window-01", ("window_64",), "tihui", ("体会", "替回"), "体会",
            (_window_context("读完这本书以后，我对耐心和长期积累有了新的体会", 64),
             _window_context("阅读完整本书后，我更能理解坚持积累带来的收获", 65)),
            (_window_context("读完这本书以后，我打算把书退回图书馆", 64),
             _window_context("阅读完整本书后，我先去办理归还手续再离开", 65))),
    _family("window-02", ("window_64",), "zongjie", ("总结", "总界"), "总结",
            (_window_context("项目收尾时需要整理总结，记录经验和问题", 64),
             _window_context("工作结束以后要汇总过程，留下经验教训", 65)),
            (_window_context("项目收尾时需要安排总结会的时间", 64),
             _window_context("工作结束以后要预订会议室并通知参会人员", 65))),
    _family("window-03", ("window_64",), "fenxi", ("分析", "反习"), "分析",
            (_window_context("拿到实验结果后先分析原因，再决定下一步", 64),
             _window_context("数据收集完成后要查找规律，然后制定后续方案", 65)),
            (_window_context("拿到实验结果后先保存文件，再等待负责人签字", 64),
             _window_context("数据收集完成后要归档材料，然后等待审批流程", 65))),
    _family("window-04", ("window_64",), "jieguo", ("结果", "借过"), "结果",
            (_window_context("测试结束后请查看结果，确认功能是否正常", 64),
             _window_context("运行完检查用例后核对输出，判断系统状态", 65)),
            (_window_context("测试结束后请从通道借过，避免堵住入口", 64),
             _window_context("运行完检查用例后先让工作人员通过，保持通道畅通", 65))),
    _family("window-05", ("window_64",), "renwu", ("任务", "人五"), "任务",
            (_window_context("今天的任务已经分配完毕，大家按计划开始工作", 64),
             _window_context("工作内容已经安排到人，现在按照排期执行", 65)),
            (_window_context("今天的人员名单已经分配完毕，大家按计划签到", 64),
             _window_context("参与者已经安排到组，现在按照名单完成报到", 65))),
    _family("window-06", ("window_64",), "huibao", ("汇报", "会报"), "汇报",
            (_window_context("周五需要汇报项目进展，让负责人了解风险", 64),
             _window_context("本周结束前要说明工作状态，特别是尚未解决的问题", 65)),
            (_window_context("周五需要召开项目例会，让负责人安排资源", 64),
             _window_context("本周结束前要组织工作会议，特别讨论资源分配", 65))),
    _family("window-07", ("window_64",), "jindu", ("进度", "近度"), "进度",
            (_window_context("请每天下班前更新进度，方便团队同步计划", 64),
             _window_context("工作结束时记得报告完成情况，让大家掌握节奏", 65)),
            (_window_context("请每天下班前更新近况，方便团队互相问候", 64),
             _window_context("工作结束时记得报告个人状态，让大家了解生活情况", 65))),
    _family("window-08", ("window_64",), "jihua", ("计划", "计画"), "计划",
            (_window_context("下个月的计划已经确定，团队开始准备资源", 64),
             _window_context("新的工作安排已经敲定，现在着手准备所需材料", 65)),
            (_window_context("下个月的计画已经确定，团队开始绘制图表", 64),
             _window_context("新的图表安排已经敲定，现在着手准备绘图材料", 65))),

    # Preference change: same topic, but the historical personal preference
    # is explicitly incompatible with the query preference.
    _family("preference-01", ("preference_change",), "jianjie", ("简洁", "剪接"), "简洁",
            ("我只需要简短结论，不必展开所有细节",
             "先给我清楚的要点即可，复杂说明可以放到后面"),
            ("这次希望看到完整推导和全部细节",
             "我更在意全面说明，结论之外的过程也要保留")),
    _family("preference-02", ("preference_change",), "qingliang", ("轻量", "清凉"), "轻量",
            ("这次优先选择占用资源少的轻量方案",
             "我更看重运行负担小，先采用精简版本"),
            ("这次优先选择功能完整的重量方案",
             "我更看重覆盖面广，宁可使用配置复杂的版本")),
    _family("preference-03", ("preference_change",), "wending", ("稳定", "问鼎"), "稳定",
            ("上线方案首先要稳定，速度稍慢也可以接受",
             "这次发布把可靠性放在第一位，性能可以适当让步"),
            ("上线方案首先要追求速度，偶尔波动也可以接受",
             "这次发布把响应时间放在第一位，稳定性可以暂时让步")),
    _family("preference-04", ("preference_change",), "shendu", ("深度", "申度"), "深度",
            ("我想要深入分析，不要只给表面结论",
             "请提供细致的原因说明，简单概括还不够"),
            ("我只想快速了解结论，不需要深入分析",
             "请直接给出简短答案，详细原因可以省略")),
    _family("preference-05", ("preference_change",), "ziyou", ("自由", "字游"), "自由",
            ("旅行安排希望留出自由时间，不必排满每个小时",
             "行程最好宽松一些，留给临时活动足够空间"),
            ("旅行安排希望固定到每个时段，不要留下空白",
             "行程最好严格一些，把每天的活动全部排定")),
    _family("preference-06", ("preference_change",), "zidong", ("自动", "自懂"), "自动",
            ("我更愿意让系统自动处理重复操作",
             "这类流程最好交给程序自行完成，减少手工步骤"),
            ("我更愿意亲自处理每一步操作",
             "这类流程最好由人工逐项确认，不要交给程序代办")),
    _family("preference-07", ("preference_change",), "suanfa", ("算法", "蒜法"), "算法",
            ("我偏好规则透明、容易解释的算法方案",
             "这次选择要能说明每一步依据，方便后续复核"),
            ("我偏好效果优先、无需解释内部过程的方案",
             "这次选择只看最终效果，内部依据不必逐项说明")),
    _family("preference-08", ("preference_change",), "biaozhun", ("标准", "表准"), "标准",
            ("报告最好遵循统一标准，便于不同团队比较",
             "文档采用一致格式更重要，这样后续审阅会更方便"),
            ("报告最好采用灵活写法，不必拘泥统一格式",
             "文档可以按作者习惯组织，不需要强行保持一致")),
)


@dataclass(frozen=True)
class BenchmarkCase:
    case_id: str
    relation: str
    family_id: str
    axes: tuple
    choice_problem: str
    candidates: tuple
    expected_candidate: str
    history_selection: str
    query_text: str
    history_text: str
    version_summary: str

    def payload(self):
        return {
            "id": self.case_id,
            "relation": self.relation,
            "expected_relation": self.relation,
            "family_id": self.family_id,
            "axes": list(self.axes),
            "choice_problem": self.choice_problem,
            "category": CATEGORY,
            "candidates": list(self.candidates),
            "expected_candidate": self.expected_candidate,
            "history_selection": self.history_selection,
            "query_text": self.query_text,
            "history_text": self.history_text,
        }

    def versionless_payload(self):
        return self.payload()


def _canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def _sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def case_version_summary(case):
    """Return the stable digest bound to every case's complete content."""
    return "%s:%s" % (
        BENCHMARK_VERSION,
        _sha256_text(_canonical_json(case.versionless_payload()))[:24],
    )


def _make_case(family, relation, ordinal, query_text, history_text,
               history_selection):
    if "window_64" in family["axes"] and relation == "hard_negative":
        # Keep every labelled boundary case as a 64/over-64 pair even when
        # the hard-negative wording has a different natural length.
        history_text = ("前" + history_text if ordinal == 1
                        else history_text[-64:])
    case_id = "%s-%s-%02d" % (relation, family["family_id"], ordinal)
    case = BenchmarkCase(
        case_id=case_id,
        relation=relation,
        family_id=family["family_id"],
        axes=family["axes"],
        choice_problem=family["choice_problem"],
        candidates=family["candidates"],
        expected_candidate=family["target"],
        history_selection=history_selection,
        query_text=query_text,
        history_text=history_text,
        version_summary="",
    )
    return replace(case, version_summary=case_version_summary(case))


def benchmark_cases():
    """Return all fixed cases in stable family/order order."""
    cases = []
    for family in FAMILY_SPECS:
        first, second = family["positive"]
        cases.extend((
            _make_case(family, "positive", 1, first, second,
                       family["target"]),
            _make_case(family, "positive", 2, second, first,
                       family["target"]),
        ))
        first, second = family["negative"]
        cases.extend((
            _make_case(family, "hard_negative", 1,
                       family["positive"][0], first,
                       family["negative_selection"]),
            _make_case(family, "hard_negative", 2,
                       family["positive"][1], second,
                       family["negative_selection"]),
        ))
    return tuple(cases)


def benchmark_manifest():
    cases = benchmark_cases()
    case_payloads = [
        dict(case.payload(), version_summary=case.version_summary)
        for case in cases
    ]
    axis_counts = {axis: sum(axis in case.axes for case in cases)
                   for axis in AXES}
    relation_counts = {
        relation: sum(case.relation == relation for case in cases)
        for relation in ("positive", "hard_negative")
    }
    digest_payload = {
        "contract": CONTRACT_ID,
        "version": BENCHMARK_VERSION,
        "schema_id": SCHEMA_ID,
        "category": CATEGORY,
        "tau": BENCHMARK_TAU,
        "k_evidence": BENCHMARK_K_EVIDENCE,
        "fixture_distractor_digest": _sha256_text(
            _canonical_json(FIXTURE_DISTRACTOR_CONTEXTS)),
        "cases": case_payloads,
    }
    return {
        "contract": CONTRACT_ID,
        "version": BENCHMARK_VERSION,
        "schema_id": SCHEMA_ID,
        "category": CATEGORY,
        "counts": {
            "total": len(cases),
            "positive": relation_counts["positive"],
            "hard_negative": relation_counts["hard_negative"],
        },
        "axis_counts": axis_counts,
        "tau": BENCHMARK_TAU,
        "k_evidence": BENCHMARK_K_EVIDENCE,
        "half_life": "inf",
        "saturation_k": BENCHMARK_SATURATION_K,
        "fixture_distractor_count": len(FIXTURE_DISTRACTOR_CONTEXTS),
        "fixture_distractor_digest": _sha256_text(
            _canonical_json(FIXTURE_DISTRACTOR_CONTEXTS)),
        "benchmark_digest": _sha256_text(_canonical_json(digest_payload)),
        "case_ids": [case.case_id for case in cases],
        "case_summaries": [
            {
                "id": case.case_id,
                "relation": case.relation,
                "axes": list(case.axes),
                "version_summary": case.version_summary,
            }
            for case in cases
        ],
        "decision_scope": "eliminate_obvious_regressions_only",
        "selection": "not_run",
        "production_enablement": "not_run",
    }


FACT_DDL = """
CREATE TABLE meta (key TEXT PRIMARY KEY NOT NULL, value TEXT NOT NULL);
CREATE TABLE commits (
  commit_id TEXT PRIMARY KEY NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE TABLE selection_events (
  event_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  event_format_version INTEGER NOT NULL,
  schema_id TEXT NOT NULL,
  canonical_segment_input TEXT NOT NULL,
  span_start INTEGER NOT NULL,
  span_end INTEGER NOT NULL,
  category TEXT NOT NULL,
  preceding_text TEXT NOT NULL,
  competition_complete INTEGER NOT NULL,
  final_selection_text TEXT NOT NULL,
  confirmation_source TEXT NOT NULL,
  trigger_keycode INTEGER,
  display_rank INTEGER NOT NULL,
  display_page INTEGER NOT NULL,
  session_id TEXT NOT NULL,
  session_seq INTEGER NOT NULL,
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_confirmed_at_ms INTEGER NOT NULL,
  utc_committed_at_ms INTEGER NOT NULL);
CREATE TABLE selection_candidates (
  event_id TEXT NOT NULL REFERENCES selection_events(event_id),
  merge_order INTEGER NOT NULL,
  text TEXT NOT NULL,
  PRIMARY KEY (event_id, merge_order));
CREATE TABLE retractions (
  retraction_id TEXT PRIMARY KEY NOT NULL,
  commit_id TEXT NOT NULL REFERENCES commits(commit_id),
  hlc_physical_ms INTEGER NOT NULL,
  hlc_logical INTEGER NOT NULL,
  utc_retracted_at_ms INTEGER NOT NULL);
"""


class SyntheticFacts:
    """One disposable facts root for one benchmark query."""

    def __init__(self, case, distractor_contexts):
        self.root = tempfile.mkdtemp(prefix="semantic_benchmark_")
        self.db_path = os.path.join(self.root, "facts.sqlite3")
        self.connection = sqlite3.connect(self.db_path)
        self.connection.executescript(FACT_DDL)
        self.connection.executemany(
            "INSERT INTO meta(key, value) VALUES(?, ?)",
            (("fact_schema_version", "1"),
             ("event_format_version", "1"),
             ("history_id", "synthetic-benchmark"),
             ("store_epoch", "synthetic-epoch"),
             ("hlc_physical_ms", "1000000"),
             ("hlc_logical", str(len(distractor_contexts) + 1)),
             ("created_at_ms", "1000000")),
        )
        self.vectors = {}
        self.target_event_id = "target-" + case.case_id
        self._insert_event(
            self.target_event_id, case.choice_problem, case.history_text,
            case.history_selection, (1000000, 1), case.candidates,
        )
        for index, context in enumerate(distractor_contexts, start=1):
            event_id = "distractor-%s-%02d" % (case.case_id, index)
            self._insert_event(
                event_id, case.choice_problem, context, case.candidates[-1],
                (1000000, index + 1), case.candidates,
            )
        self.connection.commit()

    def _insert_event(self, event_id, choice_problem, preceding_text,
                      selection, hlc, candidates):
        commit_id = "commit-" + event_id
        physical, logical = hlc
        self.connection.execute(
            "INSERT INTO commits(commit_id, utc_committed_at_ms) VALUES(?, ?)",
            (commit_id, physical),
        )
        self.connection.execute(
            "INSERT INTO selection_events(event_id, commit_id,"
            " event_format_version, schema_id, canonical_segment_input,"
            " span_start, span_end, category, preceding_text,"
            " competition_complete, final_selection_text, confirmation_source,"
            " trigger_keycode, display_rank, display_page, session_id,"
            " session_seq, hlc_physical_ms, hlc_logical,"
            " utc_confirmed_at_ms, utc_committed_at_ms)"
            " VALUES(?, ?, 1, ?, ?, 0, 1, ?, ?, 1, ?, 'explicit_current',"
            " NULL, 1, 1, 'synthetic', 0, ?, ?, ?, ?)",
            (event_id, commit_id, SCHEMA_ID, choice_problem, CATEGORY,
             preceding_text, selection, physical, logical, physical, physical),
        )
        for merge_order, text in enumerate(candidates):
            self.connection.execute(
                "INSERT INTO selection_candidates(event_id, merge_order, text)"
                " VALUES(?, ?, ?)", (event_id, merge_order, text),
            )

    def close(self):
        self.connection.close()
        shutil.rmtree(self.root, ignore_errors=True)


def _unit_vector(cosine, dimension=4):
    if not -1.0 <= cosine <= 1.0:
        raise ValueError("cosine out of range")
    remainder = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return (cosine, remainder) + (0.0,) * (dimension - 2)


def _benchmark_params():
    return OracleParams(
        tau=BENCHMARK_TAU,
        k_evidence=BENCHMARK_K_EVIDENCE,
        half_life=BENCHMARK_HALF_LIFE,
        saturation_k=BENCHMARK_SATURATION_K,
    )


def _run_oracle_case(case, reader, query_vector, vector_by_event,
                     params):
    query = OracleQuery(
        schema_id=SCHEMA_ID,
        category=CATEGORY,
        canonical_segment_input=case.choice_problem,
        candidates=case.candidates,
        query_vector=query_vector,
    )
    return compute_evidence(reader, params, query,
                            lambda event_id: vector_by_event[event_id])


def _case_passed(case, result, target_event_id):
    target = next((entry for entry in result.kept
                   if entry.event_id == target_event_id), None)
    if case.relation == "positive":
        if target is None:
            return False
        expected_index = case.candidates.index(case.expected_candidate)
        return (target.matched_candidate == expected_index
                and target.cosine > BENCHMARK_TAU)
    return target is None


def _vector_cosine(left, right):
    left = tuple(float(value) for value in left)
    right = tuple(float(value) for value in right)
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    return sum(a * b for a, b in zip(left, right)) / (left_norm * right_norm)


def _failure_detail(case, result, target_event_id, target_cosine):
    target_kept = any(entry.event_id == target_event_id
                      for entry in result.kept)
    if case.relation == "positive":
        reason = ("positive_target_below_tau"
                  if target_cosine <= BENCHMARK_TAU
                  else "positive_target_not_in_exact_top_k")
    else:
        reason = "hard_negative_target_formed_evidence"
    return {
        "case_id": case.case_id,
        "target_cosine": round(target_cosine, 6),
        "target_above_tau": target_cosine > BENCHMARK_TAU,
        "target_in_exact_top_k": target_kept,
        "reason": reason,
    }


def run_fixture_gate():
    """Run all cases with controlled vectors through the exact oracle."""
    cases = benchmark_cases()
    params = _benchmark_params()
    results = {}
    for spec in first_round_specs():
        positive_passed = 0
        negative_passed = 0
        failed = []
        for case in cases:
            fixture = SyntheticFacts(case, FIXTURE_DISTRACTOR_CONTEXTS)
            try:
                vector_by_event = {
                    fixture.target_event_id: _unit_vector(
                        0.97 if case.relation == "positive" else 0.10),
                }
                for index in range(len(FIXTURE_DISTRACTOR_CONTEXTS)):
                    event_id = "distractor-%s-%02d" % (case.case_id, index + 1)
                    vector_by_event[event_id] = _unit_vector(0.95 - index * 0.005)
                reader = FactReader(fixture.db_path)
                try:
                    result = _run_oracle_case(
                        case, reader, (1.0, 0.0, 0.0, 0.0),
                        vector_by_event, params,
                    )
                finally:
                    reader.close()
                passed = _case_passed(case, result, fixture.target_event_id)
                if case.relation == "positive":
                    positive_passed += int(passed)
                else:
                    negative_passed += int(passed)
                if not passed:
                    failed.append(case.case_id)
            finally:
                fixture.close()
        positive_total = sum(case.relation == "positive" for case in cases)
        negative_total = sum(case.relation == "hard_negative" for case in cases)
        results[spec.short_name] = {
            "representation_id": "fixture:%s" % spec.short_name,
            "positive": {
                "passed": positive_passed,
                "total": positive_total,
                "rate": positive_passed / positive_total,
                "threshold": 0.95,
            },
            "hard_negative": {
                "passed": negative_passed,
                "total": negative_total,
                "rate": negative_passed / negative_total,
                "threshold": 0.95,
            },
            "failed_case_ids": failed,
            "gate_pass": (positive_passed / positive_total >= 0.95
                          and negative_passed / negative_total >= 0.95),
        }
    return {
        "contract": CONTRACT_ID,
        "benchmark": benchmark_manifest(),
        "representations": results,
        "decision_scope": "eliminate_obvious_regressions_only",
        "selection": "not_run",
        "production_enablement": "not_run",
    }


def _real_model_vectors(model_path, contexts):
    """Load Qwen once and return all four representation vectors."""
    from hidden_state import HiddenStateExtractor
    from server import ModelState

    state = ModelState(model_path)
    extractor = HiddenStateExtractor(state)
    specs = first_round_specs()
    vectors = {spec.short_name: {} for spec in specs}
    exact_specs = [spec for spec in specs if spec.kind == "exact"]
    split_spec = next(spec for spec in specs if spec.kind == "split_reuse")
    for context in contexts:
        exact = extractor.exact_all(context)
        for spec in exact_specs:
            vectors[spec.short_name][context] = exact[spec.layer]
        vectors[split_spec.short_name][context] = extractor.split_reuse(
            context)[0]
    representation_ids = {
        spec.short_name: extractor.representation_id(spec)
        for spec in specs
    }
    identity = extractor.identity
    return vectors, representation_ids, identity, state.tokenizer


def _coverage_report(tokenizer):
    """Check that the authored boundary axes exercise the #60 seams."""
    from representations import seam_changed, split_tokenization_for

    cases = benchmark_cases()
    bpe_cases = [case for case in cases if "bpe_seam" in case.axes]
    seam_hits = 0
    for case in bpe_cases:
        prefix, prefix_ids, tail, tail_ids = split_tokenization_for(
            tokenizer, case.query_text,
        )
        exact_ids = tokenizer.encode(prefix + tail, add_special_tokens=False)
        seam_hits += int(seam_changed(prefix, prefix_ids, tail, tail_ids,
                                      exact_ids))
    window_cases = [case for case in cases if "window_64" in case.axes]
    exact_windows = sum(
        len(case.query_text) == 64 or len(case.history_text) == 64
        for case in window_cases
    )
    long_windows = sum(
        len(case.query_text) > 64 or len(case.history_text) > 64
        for case in window_cases
    )
    axis_counts = benchmark_manifest()["axis_counts"]
    return {
        "axes_present": all(axis_counts[axis] > 0 for axis in AXES),
        "bpe_cases": len(bpe_cases),
        "bpe_seam_hits": seam_hits,
        "bpe_seam_pass": seam_hits == len(bpe_cases),
        "window_cases": len(window_cases),
        "window_exact_64": exact_windows,
        "window_over_64": long_windows,
        "window_boundary_pass": (exact_windows == len(window_cases)
                                 and long_windows == len(window_cases)),
    }


def run_real_model_gate(model_path):
    """Run the gate with real Qwen vectors and synthetic temporary facts."""
    model_path = os.path.abspath(model_path)
    if not os.path.isdir(model_path) or not os.path.exists(
            os.path.join(model_path, "model.safetensors")):
        raise RuntimeError("model not found at %s" % model_path)
    cases = benchmark_cases()
    contexts = set(FIXTURE_DISTRACTOR_CONTEXTS)
    for case in cases:
        contexts.add(case.query_text)
        contexts.add(case.history_text)
    vectors, representation_ids, identity, tokenizer = _real_model_vectors(
        model_path, sorted(contexts),
    )
    coverage = _coverage_report(tokenizer)
    params = _benchmark_params()
    results = {}
    for spec in first_round_specs():
        positive_passed = 0
        negative_passed = 0
        failed = []
        failure_details = []
        for case in cases:
            fixture = SyntheticFacts(case, FIXTURE_DISTRACTOR_CONTEXTS)
            try:
                vector_by_event = {
                    fixture.target_event_id:
                        vectors[spec.short_name][case.history_text],
                }
                for index, context in enumerate(FIXTURE_DISTRACTOR_CONTEXTS,
                                                 start=1):
                    event_id = "distractor-%s-%02d" % (case.case_id, index)
                    vector_by_event[event_id] = vectors[spec.short_name][context]
                reader = FactReader(fixture.db_path)
                try:
                    result = _run_oracle_case(
                        case, reader,
                        vectors[spec.short_name][case.query_text],
                        vector_by_event, params,
                    )
                finally:
                    reader.close()
                passed = _case_passed(case, result, fixture.target_event_id)
                if case.relation == "positive":
                    positive_passed += int(passed)
                else:
                    negative_passed += int(passed)
                if not passed:
                    failed.append(case.case_id)
                    failure_details.append(_failure_detail(
                        case, result, fixture.target_event_id,
                        _vector_cosine(
                            vectors[spec.short_name][case.query_text],
                            vectors[spec.short_name][case.history_text],
                        ),
                    ))
            finally:
                fixture.close()
        positive_total = sum(case.relation == "positive" for case in cases)
        negative_total = sum(case.relation == "hard_negative" for case in cases)
        quality_pass = (positive_passed / positive_total >= 0.95
                        and negative_passed / negative_total >= 0.95)
        results[spec.short_name] = {
            "representation_id": representation_ids[spec.short_name],
            "positive": {
                "passed": positive_passed,
                "total": positive_total,
                "rate": positive_passed / positive_total,
                "threshold": 0.95,
            },
            "hard_negative": {
                "passed": negative_passed,
                "total": negative_total,
                "rate": negative_passed / negative_total,
                "threshold": 0.95,
            },
            "failed_case_ids": failed,
            "failure_details": failure_details,
            "gate_pass": quality_pass and coverage["axes_present"]
            and coverage["bpe_seam_pass"] and coverage["window_boundary_pass"],
        }
    return {
        "contract": CONTRACT_ID,
        "benchmark": benchmark_manifest(),
        "model": {
            "basename": os.path.basename(os.path.normpath(model_path)),
            "model_digest": identity.model_digest[:16],
            "tokenizer_digest": identity.tokenizer_digest[:16],
            "mlxlm_version": identity.mlxlm_version,
            "hidden_dim": identity.hidden_dim,
            "context_count": len(contexts),
        },
        "coverage": coverage,
        "representations": results,
        "decision_scope": "eliminate_obvious_regressions_only",
        "selection": "not_run",
        "production_enablement": "not_run",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true",
                        help="run the model-free exact-oracle fixture gate")
    args = parser.parse_args()
    if not args.fixture:
        parser.error("--fixture is required; the real-model gate is opt-in "
                     "through daemon/integration_semantic_benchmark.py")
    report = run_fixture_gate()
    print(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2))
    return 0 if all(item["gate_pass"] for item in
                    report["representations"].values()) else 1


if __name__ == "__main__":
    sys.exit(main())
