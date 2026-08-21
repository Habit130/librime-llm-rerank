#!/usr/bin/env python3
"""Frozen, model-free protocol for the candidate-conditioned v2 benchmark.

The v1 benchmark remains in :mod:`semantic_benchmark` and is intentionally
not edited here.  This module owns only the new v2 acceptance set, its
candidate-conditioned payloads, the seven-route declaration, v1-only Q95
calibration, and a fail-closed one-shot artifact boundary.

No function in this module loads a model, reads live facts, opens a daemon
socket, or reports v2 candidate quality.  The fixture exercises the existing
exact oracle with disposable facts and controlled vectors so protocol faults
remain testable without model dependencies.
"""

import argparse
import copy
import hashlib
import json
import math
import os
import sys
import tempfile
from dataclasses import dataclass, replace
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_DAEMON = _ROOT / "daemon"
if str(_DAEMON) not in sys.path:
    sys.path.insert(0, str(_DAEMON))

from oracle import OracleParams, OracleQuery, FactReader, compute_evidence  # noqa: E402
from semantic_benchmark import (  # noqa: E402
    AXES as V1_AXES,
    BENCHMARK_VERSION as V1_BENCHMARK_VERSION,
    CATEGORY,
    FIXTURE_DISTRACTOR_PRECEDING_TEXTS,
    SCHEMA_ID,
    SyntheticFacts as V1SyntheticFacts,
    benchmark_cases as v1_benchmark_cases,
    benchmark_manifest as v1_benchmark_manifest,
)


CONTRACT_ID = "AC-108-v1"
V2_BENCHMARK_VERSION = "candidate-conditioned-semantic-benchmark-v2"
V2_ROLE = "acceptance"
PAYLOAD_SCHEMA = "candidate-conditioned-query-history-v1"
V2_K_EVIDENCE = 8
Q95 = 0.95
STRICT_THRESHOLD_SEMANTICS = "cosine > tau"
V1_BENCHMARK_DIGEST = (
    "69205442228a14b6942e2a4de999587e893125f24f3d91e3e218a0140e2df1ec"
)
AXES = tuple(V1_AXES)
V2_FAMILY_DISTRIBUTION = {
    "negation": 10,
    "entity": 8,
    "number_flip": 8,
    "bpe_seam": 8,
    "window_64": 8,
    "preference_change": 8,
}
PRIVACY_MARKERS = (
    "/Users/",
    "~/Library/Rime",
    "facts.sqlite3",
    "socket",
    "credential",
    "private",
    "raw_model_output",
    "model.safetensors",
)
ARTIFACT_FILENAMES = frozenset({
    "semantic_benchmark_v2_manifest.json",
    "semantic_benchmark_v2_review.md",
    "semantic_benchmark_v2.frozen",
    "semantic_benchmark_v2.accepted",
    "semantic_benchmark_v2_report.json",
})


class BenchmarkProtocolError(Exception):
    """A frozen benchmark or one-shot protocol input is invalid."""


def canonical_json(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def sha256_text(value):
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_manifest_digest(manifest):
    without_digest = {
        key: value for key, value in manifest.items()
        if key != "benchmark_digest"
    }
    return sha256_text(canonical_json(without_digest))


def _last_64(text):
    return text[-64:]


def _window_fixture(core, length):
    filler = "合成二版边界记录"
    value = core
    while len(value) < length:
        value = filler + value
    if len(value) > length:
        value = value[-length:]
    return value


def _seam_fixture(core):
    return core + "，今天天气?"


@dataclass(frozen=True)
class FamilySpec:
    family_id: str
    axes: tuple
    choice_problem: str
    candidates: tuple
    target: str
    positive: tuple
    negative: tuple
    positive_intent: str
    negative_change: str
    boundary_probe: object = "none"


def _family(family_id, axis, choice_problem, candidates, target,
            positive, negative, positive_intent, negative_change,
            boundary_probe="none"):
    if axis == "window_64":
        positive = (
            _window_fixture(positive[0], 64),
            _window_fixture(positive[1], 65),
        )
        negative = (
            _window_fixture(negative[0], 65),
            _window_fixture(negative[1], 64),
        )
    elif axis == "bpe_seam":
        positive = tuple(_seam_fixture(text) for text in positive)
        negative = tuple(_seam_fixture(text) for text in negative)
        boundary_probe = {
            "suffix": "今天天气?",
            "boundary": "今/天",
            "boundary_char_index": 1,
            "tokenizer_independent": True,
        }
    return FamilySpec(
        family_id=family_id,
        axes=(axis,),
        choice_problem=choice_problem,
        candidates=tuple(candidates),
        target=target,
        positive=tuple(positive),
        negative=tuple(negative),
        positive_intent=positive_intent,
        negative_change=negative_change,
        boundary_probe=boundary_probe,
    )


# These are public synthetic Simplified-Chinese benchmark families.  The
# query side is always one of the positive texts; the negative history keeps
# the same selected candidate while changing the semantic condition.
FAMILY_SPECS = (
    # Negation: polarity changes while the candidate identity is unchanged.
    _family("v2-negation-01", "negation", "v2kaishi", ("开始", "开驶"), "开始",
            ("项目今天开始执行，团队已经完成准备",
             "准备工作已经结束，项目现在可以启动"),
            ("项目今天不要开始执行，团队还在等待",
             "准备工作尚未结束，项目暂时不能启动"),
            "开始执行项目", "禁止或延后执行"),
    _family("v2-negation-02", "negation", "v2jieshu", ("结束", "结书"), "结束",
            ("会议议程已经完成，主持人宣布会议结束",
             "最后一项讨论结束后，大家可以离场"),
            ("会议议程还没有完成，主持人要求不要结束",
             "最后一项讨论尚未完成，大家暂时不能离场"),
            "结束已完成的会议", "保持会议继续"),
    _family("v2-negation-03", "negation", "v2tongyi", ("同意", "同义"), "同意",
            ("评审意见已经确认，我同意采用这个方案",
             "看完全部说明后，我愿意接受这项安排"),
            ("评审意见还需要讨论，我不同意采用这个方案",
             "看完当前说明后，我暂时不能接受这项安排"),
            "接受方案", "拒绝方案"),
    _family("v2-negation-04", "negation", "v2jinyong", ("禁用", "金勇"), "禁用",
            ("发现安全风险后，请立即禁用这个入口",
             "风险确认以后，应当把该访问通道关掉"),
            ("检查没有发现风险，不要禁用这个入口",
             "风险已经排除，访问通道不应被关闭"),
            "关闭有风险的入口", "保留可用入口"),
    _family("v2-negation-05", "negation", "v2huifu", ("恢复", "回复"), "恢复",
            ("备份校验通过后，可以恢复服务运行",
             "故障处理完成，系统现在适合重新启动"),
            ("备份校验还没有通过，不能恢复服务运行",
             "故障处理尚未完成，系统暂时不能重新启动"),
            "重新启动服务", "继续保持停止"),
    _family("v2-negation-06", "negation", "v2baoliu", ("保留", "包留"), "保留",
            ("审计结束前请保留原始记录，不要清理文件",
             "相关调查还在进行，历史材料必须留下"),
            ("审计已经完成，可以删除原始记录，不必保留文件",
             "相关调查已经结束，历史材料不需要留下"),
            "保存审计材料", "删除审计材料"),
    _family("v2-negation-07", "negation", "v2yanzheng", ("验证", "眼正"), "验证",
            ("发布之前必须验证签名，确认文件没有被改动",
             "上线前要先检查校验信息，确保包内容可信"),
            ("这个测试包不需要验证签名，检查步骤可以跳过",
             "内部临时文件无需检查校验信息，直接继续即可"),
            "发布前检查签名", "跳过签名检查"),
    _family("v2-negation-08", "negation", "v2shanchu", ("删除", "山竹"), "删除",
            ("确认重复数据后，请删除多余的那一份",
             "去重结果已经核对，可以清掉重复记录"),
            ("这些记录还要用于追溯，请不要删除重复数据",
             "审计材料必须继续保存，重复条目也不能清掉"),
            "清除重复资料", "保留重复资料"),
    _family("v2-negation-09", "negation", "v2tijiao", ("提交", "提教"), "提交",
            ("最终检查已经完成，现在可以提交报告",
             "所有栏目都已填写，材料可以正式递交"),
            ("最终检查尚未完成，现在不要提交报告",
             "还有栏目没有填写，材料暂时不能正式递交"),
            "递交已完成的报告", "延后递交报告"),
    _family("v2-negation-10", "negation", "v2tingzhi", ("停止", "听指"), "停止",
            ("检测到异常后应立即停止任务，等待人工处理",
             "风险告警出现时先让作业停下，不再继续运行"),
            ("检测确认正常后不要停止任务，保持作业运行",
             "风险告警已经解除，作业可以继续执行"),
            "停止异常任务", "继续正常任务"),

    # Entity: the named entity changes under the same candidate identity.
    _family("v2-entity-01", "entity", "v2city_alpha", ("海城", "还成"), "海城",
            ("下周去海城参加设计展，行程已经确定",
             "设计展安排在海城举行，团队会提前到场"),
            ("下周去江城参加设计展，行程已经确定",
             "设计展安排在江城举行，团队会提前到场"),
            "前往海城参加展会", "地点改为江城"),
    _family("v2-entity-02", "entity", "v2harbor_alpha", ("东港", "冬钢"), "东港",
            ("货物将在东港装船，物流计划已经排好",
             "这批材料从东港发出，承运人已经确认"),
            ("货物将在西港装船，物流计划已经排好",
             "这批材料从西港发出，承运人已经确认"),
            "从东港装运货物", "地点改为西港"),
    _family("v2-entity-03", "entity", "v2campus_alpha", ("北苑", "被远"), "北苑",
            ("北苑校区今年扩招，招生公告已经发布",
             "新生报名将在北苑校区开始，名额正在统计"),
            ("南苑校区今年扩招，招生公告已经发布",
             "新生报名将在南苑校区开始，名额正在统计"),
            "北苑校区招生", "校区改为南苑"),
    _family("v2-entity-04", "entity", "v2station_alpha", ("青河", "清和"), "青河",
            ("列车终点是青河站，旅客要在这里下车",
             "这趟车最后抵达青河，终点信息已经确认"),
            ("列车终点是白河站，旅客要在这里下车",
             "这趟车最后抵达白河，终点信息已经确认"),
            "抵达青河终点", "终点改为白河"),
    _family("v2-entity-05", "entity", "v2factory_alpha", ("南岭", "难领"), "南岭",
            ("南岭工厂负责这批零件，生产排期已经确定",
             "这次订单交给南岭厂区，质检人员会跟进"),
            ("北岭工厂负责这批零件，生产排期已经确定",
             "这次订单交给北岭厂区，质检人员会跟进"),
            "由南岭工厂生产", "工厂改为北岭"),
    _family("v2-entity-06", "entity", "v2park_alpha", ("松园", "送远"), "松园",
            ("周末去松园参观植物展，门票已经预约",
             "植物展设在松园，家人准备在那里集合"),
            ("周末去竹园参观植物展，门票已经预约",
             "植物展设在竹园，家人准备在那里集合"),
            "前往松园看展", "地点改为竹园"),
    _family("v2-entity-07", "entity", "v2clinic_alpha", ("安宁", "按凝"), "安宁",
            ("安宁门诊下午接诊，预约号码已经发出",
             "今天的复诊安排在安宁，护士会提前通知"),
            ("康宁门诊下午接诊，预约号码已经发出",
             "今天的复诊安排在康宁，护士会提前通知"),
            "在安宁门诊复诊", "门诊改为康宁"),
    _family("v2-entity-08", "entity", "v2archive_entity_alpha", ("东原", "动员"), "东原",
            ("档案存放在东原库房，管理员已经登记",
             "这批纸质材料送到东原保管，位置已经固定"),
            ("档案存放在西原库房，管理员已经登记",
             "这批纸质材料送到西原保管，位置已经固定"),
            "材料存放于东原", "库房改为西原"),

    # Number flip: an equivalent quantity is positive; a changed quantity is
    # a hard negative even though the selected candidate stays the same.
    _family("v2-number-01", "number_flip", "v2hour_alpha", ("两小时", "量小时"), "两小时",
            ("设备充电大约需要两小时，之后可以使用",
             "这台设备预计用一百二十分钟完成充电"),
            ("设备充电大约需要三小时，之后可以使用",
             "这台设备预计用一百八十分钟完成充电"),
            "充电时长为两小时", "时长改为三小时"),
    _family("v2-number-02", "number_flip", "v2items_alpha", ("四项", "事相"), "四项",
            ("表格一共需要填写四项，提交前请逐项核对",
             "清单总共有四个栏目，所有栏目都不能遗漏"),
            ("表格一共需要填写六项，提交前请逐项核对",
             "清单总共有六个栏目，所有栏目都不能遗漏"),
            "填写四项内容", "数量改为六项"),
    _family("v2-number-03", "number_flip", "v2percent_alpha", ("百分之五", "百分之十"), "百分之五",
            ("预算预留百分之五作为机动费用，审批已经确认",
             "本次计划按百分之五的备用比例执行"),
            ("预算预留百分之十作为机动费用，审批已经确认",
             "本次计划按百分之十的备用比例执行"),
            "备用比例为百分之五", "比例改为百分之十"),
    _family("v2-number-04", "number_flip", "v2floor_alpha", ("八楼", "九楼"), "八楼",
            ("培训教室在办公楼八楼，参会者请乘电梯上去",
             "今天的课程安排在第八层，签到处就在入口旁"),
            ("培训教室在办公楼九楼，参会者请乘电梯上去",
             "今天的课程安排在第九层，签到处就在入口旁"),
            "地点为八楼", "楼层改为九楼"),
    _family("v2-number-05", "number_flip", "v2days_alpha", ("七天", "十四天"), "七天",
            ("试用期持续七天，结束后再决定是否续用",
             "这个体验安排为一周，期间可以完整测试功能"),
            ("试用期持续十四天，结束后再决定是否续用",
             "这个体验安排为两周，期间可以完整测试功能"),
            "试用期为七天", "期限改为十四天"),
    _family("v2-number-06", "number_flip", "v2rank_alpha", ("第二名", "第六名"), "第二名",
            ("这份方案在评审中获得第二名，成绩已经公布",
             "最终排名显示该方案位列亚军，评委意见一致"),
            ("这份方案在评审中获得第六名，成绩已经公布",
             "最终排名显示该方案排在第五名之后，评委意见一致"),
            "排名为第二名", "排名改为第六名"),
    _family("v2-number-07", "number_flip", "v2year_alpha", ("二〇二八", "二〇二九"), "二〇二八",
            ("合同有效期到二〇二八年底，双方已经盖章确认",
             "这份协议持续至2028年末，明年仍然有效"),
            ("合同有效期到二〇二九年底，双方已经盖章确认",
             "这份协议持续至2029年末，明年仍然有效"),
            "有效期到二〇二八", "年份改为二〇二九"),
    _family("v2-number-08", "number_flip", "v2weight_alpha", ("三百克", "三百个"), "三百克",
            ("配方需要三百克面粉，称量后再开始搅拌",
             "这份材料清单要求准备三百克面粉"),
            ("配方需要五百克面粉，称量后再开始搅拌",
             "这份材料清单要求准备五百克面粉"),
            "用量为三百克", "用量改为五百克"),

    # BPE seam: the declared 今/天 seam probe is present in every source.
    _family("v2-bpe-01", "bpe_seam", "v2publish_alpha", ("发布", "负载"), "发布",
            ("审核意见已经通过，版本准备正式发布",
             "所有检查都完成了，软件现在可以推向用户"),
            ("审核意见已经通过，系统负载需要重新测量",
             "所有检查都完成了，服务现在需要评估承载能力"),
            "发布软件版本", "语义改为系统负载", "今/天"),
    _family("v2-bpe-02", "bpe_seam", "v2storage_alpha", ("存储", "从属"), "存储",
            ("数据已经整理完毕，接下来进入存储阶段",
             "归档目录已经准备好，文件随后会保存进去"),
            ("数据已经整理完毕，接下来讨论从属关系",
             "归档目录已经准备好，文件之间的隶属需要记录"),
            "保存数据", "语义改为隶属关系", "今/天"),
    _family("v2-bpe-03", "bpe_seam", "v2deploy_alpha", ("部署", "多部"), "部署",
            ("回归测试已经通过，服务准备部署到新环境",
             "配置检查完成，应用可以安装到目标机器"),
            ("回归测试已经通过，文档需要说明多个部分",
             "配置检查完成，说明材料要拆分为不同部分"),
            "安装服务", "语义改为文档分部", "今/天"),
    _family("v2-bpe-04", "bpe_seam", "v2repair_alpha", ("修复", "休息"), "修复",
            ("缺陷已经定位，补丁将在今晚修复这个问题",
             "错误原因已经找到，下一版会把故障处理好"),
            ("缺陷已经定位，团队将在今晚休息一段时间",
             "错误原因已经找到，今晚先暂停工作再继续处理"),
            "处理软件缺陷", "语义改为休息后恢复", "今/天"),
    _family("v2-bpe-05", "bpe_seam", "v2syntax_alpha", ("语法", "鱼虾"), "语法",
            ("编译器提示语法错误，需要先改正这行代码",
             "程序解析失败，说明源文件的语法不符合规则"),
            ("池塘里的鱼虾数量增加，需要调整投喂安排",
             "水面观察记录显示鱼虾活跃，管理员准备补充饲料"),
            "检查代码语法", "语义改为水生生物", "今/天"),
    _family("v2-bpe-06", "bpe_seam", "v2review_alpha", ("评审", "平躺"), "评审",
            ("设计稿已经完成，下午安排评审并收集意见",
             "方案材料已经齐全，会议将讨论修改建议"),
            ("长途行走之后需要平躺休息，避免突然起身",
             "体力恢复以前先保持平躺状态，再安排活动"),
            "审查设计方案", "语义改为身体姿态", "今/天"),
    _family("v2-bpe-07", "bpe_seam", "v2archive_bpe_alpha", ("归档", "硅钢"), "归档",
            ("项目结束后请归档资料，方便以后查阅",
             "完成验收以后把文档统一保存到档案目录"),
            ("设备材料包含硅钢片，需要按批次清点",
             "仓库收到新一批硅钢，质检人员准备抽样"),
            "保存项目档案", "语义改为硅钢材料", "今/天"),
    _family("v2-bpe-08", "bpe_seam", "v2audit_alpha", ("审计", "身体"), "审计",
            ("季度账目已经整理，接下来开始审计流程",
             "财务资料全部齐备，检查人员将核对每笔记录"),
            ("运动计划强调保护身体，训练前要充分热身",
             "健康记录已经更新，教练提醒大家注意身体状态"),
            "检查财务记录", "语义改为身体状况", "今/天"),

    # Window boundary: authored sources contain one exact-64 and one over-64
    # context in every pair; payloads always retain only the last 64 chars.
    _family("v2-window-01", "window_64", "v2summary_alpha", ("总结", "总数"), "总结",
            ("项目收尾时整理总结，记录经验和待改进的问题",
             "工作结束以后汇总过程，留下清晰的经验说明"),
            ("项目收尾时安排总结会的时间，通知相关人员参加",
             "工作结束以后预订会议室，并提醒大家按时到场"),
            "整理项目总结", "语义改为安排总结会议"),
    _family("v2-window-02", "window_64", "v2analysis_alpha", ("分析", "反习"), "分析",
            ("拿到实验结果后先分析原因，再决定后续方案",
             "数据收集完成后查找规律，随后制定下一步计划"),
            ("拿到实验结果后先保存文件，再等待负责人签字",
             "数据收集完成后归档材料，随后等待审批流程"),
            "分析实验结果", "语义改为归档并审批"),
    _family("v2-window-03", "window_64", "v2handoff_alpha", ("交接", "交界"), "交接",
            ("值班结束前完成交接，把未完成事项说明清楚",
             "轮班人员已经见面，工作记录会逐项交给下一班"),
            ("地图显示两地交界，需要补充边界标记",
             "保护区位于两县交界，工作人员准备确认边界"),
            "交接工作记录", "语义改为地理边界"),
    _family("v2-window-04", "window_64", "v2inventory_alpha", ("盘点", "判定"), "盘点",
            ("月底需要盘点库存，核对系统和实物数量",
             "仓库清单已经打印，工作人员将逐件清查物料"),
            ("月底需要判定验收结果，等待负责人给出结论",
             "会议结束后判定方案是否通过，负责人会公布结论"),
            "清点库存", "语义改为作出验收判定"),
    _family("v2-window-05", "window_64", "v2schedule_alpha", ("排期", "排队"), "排期",
            ("新版本排期已经确定，团队按日期准备发布工作",
             "开发计划排好了，每个任务都有明确的交付时间"),
            ("新版本发布现场需要排队，团队按顺序准备入场工作",
             "开发计划排好了，参会人员需要按号码依次入场"),
            "安排开发日期", "语义改为现场排队"),
    _family("v2-window-06", "window_64", "v2handover_alpha", ("移交", "遗失"), "移交",
            ("文件确认无误后移交给档案员，双方留下签收记录",
             "资料审核完成，下一步由专人接收并保管"),
            ("文件在运输途中遗失，需要登记并重新补办",
             "资料审核完成后发现遗失，下一步先查找运输记录"),
            "正式移交资料", "语义改为遗失与追查"),
    _family("v2-window-07", "window_64", "v2forecast_alpha", ("预测", "预设"), "预测",
            ("模型需要预测下周需求，输入数据已经准备好",
             "计划先估计市场变化，再安排采购数量"),
            ("模型需要预设下周需求，输入数据已经准备好",
             "计划先固定默认参数，再安排采购数量"),
            "估计未来需求", "语义改为设定默认值"),
    _family("v2-window-08", "window_64", "v2dispatch_alpha", ("调度", "雕塑"), "调度",
            ("高峰期需要调度车辆，避免入口出现拥堵",
             "交通中心会按实时情况安排车辆分流"),
            ("展厅需要雕塑作品，入口区域要重新布置",
             "艺术团队准备制作雕塑，现场要安排运输"),
            "安排车辆运行", "语义改为雕塑展示"),

    # Preference change: the topic stays close while the desired trade-off
    # changes, so candidate identity alone cannot make the history positive.
    _family("v2-preference-01", "preference_change", "v2brief_alpha", ("简明", "简化"), "简明",
            ("这次报告希望简明，先给结论再补充必要依据",
             "阅读时我更需要清楚要点，不必铺开所有细节"),
            ("这次报告希望完整，先给全部推导再概括结论",
             "阅读时我更需要详细过程，不能只保留几个要点"),
            "偏好简短清楚", "偏好完整详尽"),
    _family("v2-preference-02", "preference_change", "v2light_alpha", ("轻量", "清凉"), "轻量",
            ("部署方案优先选择轻量版本，机器资源比较有限",
             "这次更看重运行负担小，先使用精简配置"),
            ("部署方案优先选择完整版本，可以接受更高资源消耗",
             "这次更看重功能覆盖广，宁可使用复杂配置"),
            "偏好低资源方案", "偏好功能完整方案"),
    _family("v2-preference-03", "preference_change", "v2stable_alpha", ("稳定", "问鼎"), "稳定",
            ("上线方案首先要稳定，速度慢一些也可以接受",
             "这次发布把可靠性放在第一位，性能可以适当让步"),
            ("上线方案首先要快速，偶尔波动也可以接受",
             "这次发布把响应时间放在第一位，稳定性可以暂时让步"),
            "偏好可靠性", "偏好速度"),
    _family("v2-preference-04", "preference_change", "v2transparent_alpha", ("透明", "通明"), "透明",
            ("选择方案时希望规则透明，每一步依据都能解释",
             "后续复核需要看懂决策过程，不能只看最终结果"),
            ("选择方案时希望效果优先，内部过程不必全部解释",
             "后续复核只需关注最终结果，不要求公开每一步依据"),
            "偏好可解释规则", "偏好效果优先"),
    _family("v2-preference-05", "preference_change", "v2manual_alpha", ("自动", "自主"), "自动",
            ("重复工作希望自动处理，减少每天的手工步骤",
             "这类流程交给程序自行完成，可以节省操作时间"),
            ("重复工作希望人工处理，每一步都由工作人员确认",
             "这类流程不要交给程序代办，需要逐项手动检查"),
            "偏好自动处理", "偏好人工处理"),
    _family("v2-preference-06", "preference_change", "v2flexible_alpha", ("灵活", "零件"), "灵活",
            ("行程安排希望灵活，留出时间应对临时变化",
             "旅行计划不要排得太满，临时调整会更方便"),
            ("行程安排希望固定，每个时段都提前排好活动",
             "旅行计划需要严格执行，不要留下临时变更空间"),
            "偏好灵活安排", "偏好固定安排"),
    _family("v2-preference-07", "preference_change", "v2thorough_alpha", ("深入", "全面"), "深入",
            ("调查报告需要深入分析，不能只给表面结论",
             "请说明原因和背景，简单概括还不足以决策"),
            ("调查报告只要快速结论，不需要展开全部原因",
             "请直接说明结果，详细背景可以暂时省略"),
            "偏好深入分析", "偏好快速结论"),
    _family("v2-preference-08", "preference_change", "v2standard_alpha", ("标准", "表准"), "标准",
            ("报告最好采用统一规范，方便不同团队相互比较",
             "文档使用一致格式更重要，后续审阅会更容易"),
            ("报告最好允许自由写法，不必拘泥统一规范",
             "文档可以按作者习惯组织，不需要强行保持一致"),
            "偏好统一格式", "偏好自由格式"),
)


@dataclass(frozen=True)
class BenchmarkCaseV2:
    case_id: str
    relation: str
    family_id: str
    axes: tuple
    choice_problem: str
    candidates: tuple
    query_candidate: str
    historical_selected_candidate: str
    expected_relation: str
    query_preceding_text: str
    recorded_preceding_text: str
    source_query_text: str
    source_recorded_text: str
    positive_intent: str
    negative_change: str
    boundary_probe: object
    version_summary: str = ""

    @property
    def history_selection(self):
        return self.historical_selected_candidate

    def payload(self):
        return {
            "payload_schema": PAYLOAD_SCHEMA,
            "benchmark_version": V2_BENCHMARK_VERSION,
            "id": self.case_id,
            "relation": self.relation,
            "expected_relation": self.expected_relation,
            "family_id": self.family_id,
            "axes": list(self.axes),
            "choice_problem": self.choice_problem,
            "category": CATEGORY,
            "candidates": list(self.candidates),
            "query_candidate": self.query_candidate,
            "historical_selected_candidate": self.historical_selected_candidate,
            "query_preceding_text": self.query_preceding_text,
            "recorded_preceding_text": self.recorded_preceding_text,
            "query": {
                "preceding_text": self.query_preceding_text,
                "candidate": self.query_candidate,
            },
            "history": {
                "preceding_text": self.recorded_preceding_text,
                "selected_candidate": self.historical_selected_candidate,
            },
            "source_lengths": {
                "query": len(self.source_query_text),
                "history": len(self.source_recorded_text),
            },
            "source_texts": {
                "query": self.source_query_text,
                "history": self.source_recorded_text,
            },
            "semantic_review": {
                "positive_intent": self.positive_intent,
                "negative_change": self.negative_change,
            },
            "boundary_probe": self.boundary_probe,
        }


def _make_case(family, relation, ordinal, query_text, history_text):
    case = BenchmarkCaseV2(
        case_id="%s-%s-%02d" % (relation, family.family_id, ordinal),
        relation=relation,
        family_id=family.family_id,
        axes=family.axes,
        choice_problem=family.choice_problem,
        candidates=family.candidates,
        query_candidate=family.target,
        historical_selected_candidate=family.target,
        expected_relation=relation,
        query_preceding_text=_last_64(query_text),
        recorded_preceding_text=_last_64(history_text),
        source_query_text=query_text,
        source_recorded_text=history_text,
        positive_intent=family.positive_intent,
        negative_change=family.negative_change,
        boundary_probe=family.boundary_probe,
    )
    return replace(case, version_summary=sha256_text(
        canonical_json(case.payload()))[:24])


def family_specs_v2():
    return tuple(FAMILY_SPECS)


def benchmark_cases_v2():
    cases = []
    for family in FAMILY_SPECS:
        cases.extend((
            _make_case(family, "positive", 1,
                       family.positive[0], family.positive[1]),
            _make_case(family, "positive", 2,
                       family.positive[1], family.positive[0]),
            _make_case(family, "hard_negative", 1,
                       family.positive[0], family.negative[0]),
            _make_case(family, "hard_negative", 2,
                       family.positive[1], family.negative[1]),
        ))
    return tuple(cases)


def _family_payload(family):
    return {
        "family_id": family.family_id,
        "axes": list(family.axes),
        "choice_problem": family.choice_problem,
        "candidates": list(family.candidates),
        "target": family.target,
        "positive": list(family.positive),
        "negative": list(family.negative),
        "positive_intent": family.positive_intent,
        "negative_change": family.negative_change,
        "boundary_probe": family.boundary_probe,
    }


def _v1_snapshot():
    manifest = v1_benchmark_manifest()
    cases = v1_benchmark_cases()
    if manifest.get("benchmark_digest") != V1_BENCHMARK_DIGEST:
        raise BenchmarkProtocolError("accepted v1 benchmark digest changed")
    if len(cases) != 200 or manifest.get("counts") != {
            "total": 200, "positive": 100, "hard_negative": 100}:
        raise BenchmarkProtocolError("accepted v1 benchmark counts changed")
    if manifest.get("axis_counts") != {
            "negation": 40, "entity": 32, "number_flip": 32,
            "bpe_seam": 32, "window_64": 32,
            "preference_change": 32}:
        raise BenchmarkProtocolError("accepted v1 axis distribution changed")
    family_ids = tuple(family["family_id"] for family in _v1_families())
    if len(family_ids) != 50 or len(set(family_ids)) != 50:
        raise BenchmarkProtocolError("accepted v1 family IDs changed")
    return {
        "contract": "AC-69-v1",
        "version": V1_BENCHMARK_VERSION,
        "family_count": 50,
        "case_count": 200,
        "digest": V1_BENCHMARK_DIGEST,
        "family_ids": family_ids,
        "case_ids": tuple(case.case_id for case in cases),
    }


def _v1_families():
    from semantic_benchmark import FAMILY_SPECS as v1_families
    return tuple(v1_families)


def _v1_text_pairs():
    pairs = set()
    for family in _v1_families():
        for relation in (family["positive"], family["negative"]):
            pairs.add(frozenset(relation))
    return pairs


def _v1_choice_sets():
    return {
        (family["choice_problem"], frozenset(family["candidates"]))
        for family in _v1_families()
    }


def validate_v2_cases():
    v1 = _v1_snapshot()
    families = family_specs_v2()
    cases = benchmark_cases_v2()
    if len(families) != 50:
        raise BenchmarkProtocolError("v2 must contain exactly 50 families")
    if len(cases) != 200:
        raise BenchmarkProtocolError("v2 must expand to exactly 200 cases")
    ids = [family.family_id for family in families]
    if len(set(ids)) != len(ids) or set(ids) & set(v1["family_ids"]):
        raise BenchmarkProtocolError("v2 family IDs overlap v1 or duplicate")
    if {axis: sum(axis in family.axes for family in families)
            for axis in AXES} != V2_FAMILY_DISTRIBUTION:
        raise BenchmarkProtocolError("v2 family axis distribution changed")
    text_pairs = _v1_text_pairs()
    choice_sets = _v1_choice_sets()
    seen_text_pairs = set()
    seen_choice_sets = set()
    for family in families:
        if len(family.positive) != 2 or len(family.negative) != 2:
            raise BenchmarkProtocolError(
                "family %s does not have two directions per relation"
                % family.family_id)
        if len(family.axes) != 1 or family.axes[0] not in AXES:
            raise BenchmarkProtocolError(
                "family %s has an unknown or composite axis" % family.family_id)
        choice_set = (family.choice_problem, frozenset(family.candidates))
        if choice_set in seen_choice_sets:
            raise BenchmarkProtocolError(
                "v2 choice problem/candidate set is duplicated")
        seen_choice_sets.add(choice_set)
        for relation in (family.positive, family.negative):
            if frozenset(relation) in text_pairs:
                raise BenchmarkProtocolError(
                    "family %s reuses a v1 text pair" % family.family_id)
            pair = frozenset(relation)
            if pair in seen_text_pairs:
                raise BenchmarkProtocolError("v2 text pair is duplicated")
            seen_text_pairs.add(pair)
        if choice_set in choice_sets:
            raise BenchmarkProtocolError(
                "family %s reuses a v1 choice problem" % family.family_id)
    case_ids = [case.case_id for case in cases]
    if len(case_ids) != len(set(case_ids)):
        raise BenchmarkProtocolError("v2 case IDs are not unique")
    if sum(case.relation == "positive" for case in cases) != 100:
        raise BenchmarkProtocolError("v2 positive count changed")
    if sum(case.relation == "hard_negative" for case in cases) != 100:
        raise BenchmarkProtocolError("v2 hard-negative count changed")
    for case in cases:
        if case.expected_relation != case.relation:
            raise BenchmarkProtocolError("case relation is not explicit")
        if case.query_candidate != case.historical_selected_candidate:
            raise BenchmarkProtocolError(
                "candidate identity differs between query and history")
        if case.query_candidate not in case.candidates:
            raise BenchmarkProtocolError("query candidate is not in candidate set")
        if case.query_preceding_text != _last_64(case.source_query_text):
            raise BenchmarkProtocolError("query context is not last-64")
        if case.recorded_preceding_text != _last_64(case.source_recorded_text):
            raise BenchmarkProtocolError("history context is not last-64")
        if case.version_summary != sha256_text(
                canonical_json(case.payload()))[:24]:
            raise BenchmarkProtocolError("case version summary mismatch")
        if not case.positive_intent or not case.negative_change:
            raise BenchmarkProtocolError("case semantic review labels are missing")
        if "bpe_seam" in case.axes:
            probe = case.boundary_probe
            if not isinstance(probe, dict) or probe != {
                    "suffix": "今天天气?",
                    "boundary": "今/天",
                    "boundary_char_index": 1,
                    "tokenizer_independent": True,
            }:
                raise BenchmarkProtocolError("BPE seam probe drifted")
            if not case.source_query_text.endswith(probe["suffix"]) or \
                    not case.source_recorded_text.endswith(probe["suffix"]):
                raise BenchmarkProtocolError("BPE seam suffix is missing")
        serialized = canonical_json(case.payload())
        for marker in PRIVACY_MARKERS:
            if marker in serialized:
                raise BenchmarkProtocolError("v2 case contains a live marker")
    for family in families:
        family_cases = [case for case in cases
                        if case.family_id == family.family_id]
        positive = [case for case in family_cases
                    if case.relation == "positive"]
        negative = [case for case in family_cases
                    if case.relation == "hard_negative"]
        if {case.source_query_text for case in positive} != set(family.positive):
            raise BenchmarkProtocolError("positive direction content drifted")
        if {case.source_recorded_text for case in positive} != set(family.positive):
            raise BenchmarkProtocolError("positive history content drifted")
        if {case.source_query_text for case in negative} != set(family.positive):
            raise BenchmarkProtocolError("hard-negative query content drifted")
        if {case.source_recorded_text for case in negative} != set(family.negative):
            raise BenchmarkProtocolError("hard-negative history content drifted")
    return cases


def _axis_counts(cases):
    return {axis: sum(axis in case.axes for case in cases) for axis in AXES}


def route_matrix():
    """Return the exact seven routes declared by the v2 acceptance round."""
    return copy.deepcopy(FROZEN_ROUTE_MATRIX)


FROZEN_ROUTE_MATRIX = (
    {
        "route_id": "dedicated_qwen3_embedding_0_6b",
        "kind": "dedicated_embedding",
        "model": "Qwen3-Embedding-0.6B",
        "payload": PAYLOAD_SCHEMA,
        "instruction": "Represent the candidate-conditioned query for semantic retrieval.",
        "pooling": "model_output",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:dedicated-qwen3-embedding-0.6b:payload="
            "candidate-conditioned-query-history-v1:instruction=represent-"
            "candidate-conditioned-query-for-semantic-retrieval:window=64:pool=model_output:"
            "format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "dedicated_bge_m3",
        "kind": "dedicated_embedding",
        "model": "BGE-M3",
        "payload": PAYLOAD_SCHEMA,
        "instruction": "none",
        "pooling": "model_output",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:dedicated-bge-m3:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:"
            "pool=model_output:format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "qwen_l14_candidate_span_mean",
        "kind": "qwen_hidden_state",
        "model": "Qwen3-0.6B-Base",
        "instruction": "none",
        "payload": PAYLOAD_SCHEMA,
        "layer": 14,
        "pooling": "candidate_span_mean",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:qwen3-0.6b-base:l14:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:pool="
            "candidate_span_mean:format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "qwen_l21_candidate_span_mean",
        "kind": "qwen_hidden_state",
        "model": "Qwen3-0.6B-Base",
        "instruction": "none",
        "payload": PAYLOAD_SCHEMA,
        "layer": 21,
        "pooling": "candidate_span_mean",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:qwen3-0.6b-base:l21:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:pool="
            "candidate_span_mean:format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "qwen_l28_candidate_span_mean",
        "kind": "qwen_hidden_state",
        "model": "Qwen3-0.6B-Base",
        "instruction": "none",
        "payload": PAYLOAD_SCHEMA,
        "layer": 28,
        "pooling": "candidate_span_mean",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:qwen3-0.6b-base:l28:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:pool="
            "candidate_span_mean:format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "qwen_l28_last_candidate_token_control",
        "kind": "qwen_hidden_state_control",
        "model": "Qwen3-0.6B-Base",
        "instruction": "none",
        "payload": PAYLOAD_SCHEMA,
        "layer": 28,
        "pooling": "last_candidate_token",
        "candidate_conditioned": True,
        "control": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 1024,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:qwen3-0.6b-base:l28-control:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:pool="
            "last_candidate_token:format=fp32_l2_normalized:dim=1024:metric=cosine",
    },
    {
        "route_id": "qwen_global_l14_l21_l28_projection_3072_to_256",
        "kind": "qwen_linear_projection",
        "model": "Qwen3-0.6B-Base",
        "instruction": "none",
        "payload": PAYLOAD_SCHEMA,
        "layers": [14, 21, 28],
        "pooling": "candidate_span_mean_concat",
        "candidate_conditioned": True,
        "window_chars": 64,
        "vector_format": "fp32_l2_normalized",
        "dimension": 256,
        "metric": "cosine",
        "representation_id":
            "ac108-v2:qwen3-0.6b-base:global-projection:payload="
            "candidate-conditioned-query-history-v1:instruction=none:window=64:pool="
            "candidate_span_mean_concat:projection=linear3072to256:"
            "format=fp32_l2_normalized:dim=256:metric=cosine",
        "projection": {"kind": "linear", "input_dim": 3072,
                        "output_dim": 256},
    },
)


def route_matrix_digest(routes=None):
    routes = route_matrix() if routes is None else routes
    return sha256_text(canonical_json(routes))


def validate_route_matrix(routes):
    expected = route_matrix()
    if not isinstance(routes, (list, tuple)):
        raise BenchmarkProtocolError("route matrix must be a list")
    if canonical_json(routes) != canonical_json(expected):
        raise BenchmarkProtocolError(
            "route matrix is missing, extra, or drifted from AC-108")
    if sum(route["kind"] == "dedicated_embedding" for route in routes) != 2:
        raise BenchmarkProtocolError("route matrix needs two dedicated routes")
    if len(routes) != 7:
        raise BenchmarkProtocolError("route matrix must contain seven routes")
    return True


def benchmark_manifest_v2():
    cases = validate_v2_cases()
    v1 = _v1_snapshot()
    routes = route_matrix()
    case_payloads = [
        dict(case.payload(), version_summary=case.version_summary)
        for case in cases
    ]
    relation_counts = {
        relation: sum(case.relation == relation for case in cases)
        for relation in ("positive", "hard_negative")
    }
    core = {
        "contract": CONTRACT_ID,
        "benchmark_version": V2_BENCHMARK_VERSION,
        "benchmark_role": V2_ROLE,
        "payload_schema": PAYLOAD_SCHEMA,
        "schema_id": SCHEMA_ID,
        "category": CATEGORY,
        "v1": {
            "contract": v1["contract"],
            "benchmark_version": v1["version"],
            "family_count": v1["family_count"],
            "case_count": v1["case_count"],
            "benchmark_digest": v1["digest"],
            "family_ids": list(v1["family_ids"]),
            "case_ids": list(v1["case_ids"]),
        },
        "v2": {
            "family_count": len(FAMILY_SPECS),
            "case_count": len(cases),
            "relation_counts": relation_counts,
            "axis_counts": _axis_counts(cases),
            "families": [_family_payload(family) for family in FAMILY_SPECS],
            "cases": case_payloads,
        },
        "route_matrix": routes,
        "route_matrix_digest": route_matrix_digest(routes),
        "k_evidence": V2_K_EVIDENCE,
        "threshold_protocol": {
            "source": "v1_hard_negative_cosines",
            "source_case_count": 100,
            "quantile": "Q95",
            "quantile_method": "nearest_rank",
            "comparison": STRICT_THRESHOLD_SEMANTICS,
            "v2_cases_in_calibration": False,
        },
        "fixture_distractors": {
            "count": len(FIXTURE_DISTRACTOR_PRECEDING_TEXTS),
            "digest": sha256_text(canonical_json(
                FIXTURE_DISTRACTOR_PRECEDING_TEXTS)),
        },
        "case_summaries": [
            {
                "id": case.case_id,
                "relation": case.relation,
                "family_id": case.family_id,
                "axes": list(case.axes),
                "version_summary": case.version_summary,
            }
            for case in cases
        ],
        "review_table_digest": sha256_text(render_review_table(cases)),
        "selection": "not_run",
        "production_enablement": "not_run",
    }
    manifest = dict(core)
    manifest["benchmark_digest"] = canonical_manifest_digest(manifest)
    return manifest


def render_review_table(cases=None):
    """Render a stable, desensitized table for independent semantic review."""
    cases = benchmark_cases_v2() if cases is None else cases
    lines = [
        "# AC-108 v2 Semantic Review Table",
        "",
        "Synthetic Simplified-Chinese cases only; no live user text.",
        "",
        "| Case | Axis | Relation | Choice problem | Candidate | Query context | Historical context | Semantic relation | Source lengths |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for case in cases:
        values = (
            case.case_id,
            ",".join(case.axes),
            case.relation,
            case.choice_problem,
            case.query_candidate,
            case.query_preceding_text,
            case.recorded_preceding_text,
            (case.positive_intent if case.relation == "positive"
             else case.negative_change),
            "%d/%d" % (len(case.source_query_text),
                        len(case.source_recorded_text)),
        )
        lines.append("| " + " | ".join(
            value.replace("|", "\\|").replace("\n", " ")
            for value in values) + " |")
    return "\n".join(lines) + "\n"


@dataclass(frozen=True)
class CalibrationObservation:
    case_id: str
    benchmark_version: str
    relation: str
    cosine: float


def _observation(value):
    if isinstance(value, CalibrationObservation):
        return value
    if not isinstance(value, dict):
        raise BenchmarkProtocolError("calibration observation must be an object")
    required = ("case_id", "benchmark_version", "relation", "cosine")
    if any(key not in value for key in required):
        raise BenchmarkProtocolError("calibration observation is incomplete")
    return CalibrationObservation(
        case_id=value["case_id"],
        benchmark_version=value["benchmark_version"],
        relation=value["relation"],
        cosine=value["cosine"],
    )


def nearest_rank_q95(values):
    if not values:
        raise BenchmarkProtocolError("Q95 needs observations")
    index = int(math.ceil(Q95 * len(values))) - 1
    return sorted(values)[max(0, min(index, len(values) - 1))]


def calibrate_v1_q95(observations):
    """Calibrate one route from exactly the 100 v1 hard-negative cases."""
    observations = tuple(_observation(value) for value in observations)
    v1_ids = set(_v1_snapshot()["case_ids"])
    v1_negative_ids = {
        case.case_id for case in v1_benchmark_cases()
        if case.relation == "hard_negative"
    }
    if len(observations) != 100:
        raise BenchmarkProtocolError(
            "v1 Q95 calibration requires exactly 100 observations")
    seen = set()
    values = []
    for observation in observations:
        if observation.benchmark_version != V1_BENCHMARK_VERSION:
            raise BenchmarkProtocolError(
                "calibration input is not from the frozen v1 benchmark")
        if observation.relation != "hard_negative":
            raise BenchmarkProtocolError(
                "calibration input must be v1 hard-negative")
        if observation.case_id not in v1_ids or \
                observation.case_id not in v1_negative_ids:
            raise BenchmarkProtocolError(
                "calibration input contains a non-v1 hard-negative case")
        if observation.case_id in seen:
            raise BenchmarkProtocolError("duplicate calibration case ID")
        seen.add(observation.case_id)
        if isinstance(observation.cosine, bool):
            raise BenchmarkProtocolError("cosine must be numeric")
        try:
            cosine = float(observation.cosine)
        except (TypeError, ValueError) as error:
            raise BenchmarkProtocolError("cosine must be numeric") from error
        if not math.isfinite(cosine) or not -1.0 <= cosine <= 1.0:
            raise BenchmarkProtocolError("cosine must be finite and in [-1, 1]")
        values.append(cosine)
    if seen != v1_negative_ids:
        raise BenchmarkProtocolError("v1 hard-negative calibration set is incomplete")
    return {
        "source_benchmark_version": V1_BENCHMARK_VERSION,
        "source_relation": "hard_negative",
        "source_case_count": len(observations),
        "source_case_ids_digest": sha256_text(canonical_json(
            [observation.case_id for observation in observations])),
        "quantile": "Q95",
        "quantile_method": "nearest_rank",
        "tau": nearest_rank_q95(values),
        "comparison": STRICT_THRESHOLD_SEMANTICS,
    }


def strict_cosine_above_threshold(cosine, tau):
    try:
        cosine = float(cosine)
        tau = float(tau)
    except (TypeError, ValueError) as error:
        raise BenchmarkProtocolError("threshold inputs must be numeric") from error
    if not math.isfinite(cosine) or not math.isfinite(tau):
        raise BenchmarkProtocolError("threshold inputs must be finite")
    return cosine > tau


def _fixture_calibration_observations(route_index):
    negative_cases = [
        case for case in v1_benchmark_cases()
        if case.relation == "hard_negative"
    ]
    return tuple({
        "case_id": case.case_id,
        "benchmark_version": V1_BENCHMARK_VERSION,
        "relation": "hard_negative",
        "cosine": 0.60 + route_index * 0.01 + (index % 10) * 0.01,
    } for index, case in enumerate(negative_cases))


def _unit_vector(cosine):
    if not -1.0 <= cosine <= 1.0:
        raise BenchmarkProtocolError("fixture cosine is out of range")
    remainder = math.sqrt(max(0.0, 1.0 - cosine * cosine))
    return (cosine, remainder, 0.0, 0.0)


def _fixture_route_gate(cases, route_index, tau):
    positive_passed = 0
    negative_passed = 0
    kept_at_k = 0
    equality_excluded = 0
    top_k_order_passed = 0
    params = OracleParams(tau=tau, k_evidence=V2_K_EVIDENCE,
                          half_life=float("inf"), saturation_k=1.0)
    for case in cases:
        fixture = V1SyntheticFacts(case, FIXTURE_DISTRACTOR_PRECEDING_TEXTS)
        try:
            vector_by_event = {
                fixture.target_event_id: _unit_vector(
                    0.99 if case.relation == "positive" else 0.10),
            }
            for index in range(len(FIXTURE_DISTRACTOR_PRECEDING_TEXTS)):
                event_id = "distractor-%s-%02d" % (case.case_id, index + 1)
                cosine = (tau if index == len(FIXTURE_DISTRACTOR_PRECEDING_TEXTS) - 1
                          else tau + (1.0 - tau) * (0.80 - index * 0.03))
                vector_by_event[event_id] = _unit_vector(cosine)
            reader = FactReader(fixture.db_path)
            try:
                result = compute_evidence(
                    reader,
                    params,
                    OracleQuery(
                        schema_id=SCHEMA_ID,
                        category=CATEGORY,
                        canonical_segment_input=case.choice_problem,
                        candidates=case.candidates,
                        query_vector=(1.0, 0.0, 0.0, 0.0),
                    ),
                    lambda event_id: vector_by_event[event_id],
                )
            finally:
                reader.close()
            kept_at_k += int(len(result.kept) == V2_K_EVIDENCE)
            equality_id = fixture.threshold_probe_event_id
            equality_excluded += int(
                equality_id not in {entry.event_id for entry in result.kept})
            target = next((entry for entry in result.kept
                           if entry.event_id == fixture.target_event_id), None)
            expected_ids = (
                ([fixture.target_event_id] if case.relation == "positive" else [])
                + ["distractor-%s-%02d" % (case.case_id, index)
                   for index in range(1, 8 if case.relation == "positive" else 9)]
            )
            top_k_order_passed += int(
                [entry.event_id for entry in result.kept] == expected_ids)
            if case.relation == "positive":
                positive_passed += int(
                    target is not None
                    and target.matched_candidate == case.candidates.index(
                        case.query_candidate)
                    and strict_cosine_above_threshold(target.cosine, tau))
            else:
                negative_passed += int(target is None)
        finally:
            fixture.close()
    positive_total = sum(case.relation == "positive" for case in cases)
    negative_total = sum(case.relation == "hard_negative" for case in cases)
    return {
        "route_index": route_index,
        "positive": {"passed": positive_passed, "total": positive_total,
                      "rate": positive_passed / positive_total},
        "hard_negative": {"passed": negative_passed, "total": negative_total,
                           "rate": negative_passed / negative_total},
        "exact_top_k": {"k_evidence": V2_K_EVIDENCE,
                        "kept_at_k": kept_at_k},
        "strict_equality_probe_excluded": equality_excluded,
        "top_k_order_passed": top_k_order_passed,
        "gate_pass": positive_passed / positive_total >= 0.95
        and negative_passed / negative_total >= 0.95
        and kept_at_k == len(cases)
        and equality_excluded == len(cases)
        and top_k_order_passed == len(cases),
    }


def _run_fixture_gate(manifest):
    """Run protocol coverage after the frozen manifest is established."""
    validate_route_matrix(manifest["route_matrix"])
    cases = validate_v2_cases()
    routes = {}
    calibrations = {}
    for route_index, route in enumerate(manifest["route_matrix"]):
        observations = _fixture_calibration_observations(route_index)
        calibration = calibrate_v1_q95(observations)
        calibrations[route["route_id"]] = {
            "calibration": calibration,
            "observations": list(observations),
        }
        routes[route["route_id"]] = _fixture_route_gate(
            cases, route_index, calibration["tau"])
    return {"routes": routes, "calibrations": calibrations}


def run_fixture_gate(artifact_dir):
    """Run protocol coverage only inside a previously frozen boundary."""
    manifest = verify_frozen_inputs(artifact_dir)
    return _run_fixture_gate(manifest)


def _one_shot_identity(manifest):
    return sha256_text(canonical_json({
        "contract": manifest["contract"],
        "benchmark_version": manifest["benchmark_version"],
        "benchmark_digest": manifest["benchmark_digest"],
        "route_matrix_digest": manifest["route_matrix_digest"],
    }))


def build_fixture_report(artifact_dir, fixture=None):
    manifest = verify_frozen_inputs(artifact_dir)
    fixture = _run_fixture_gate(manifest) if fixture is None else fixture
    report = {
        "contract": CONTRACT_ID,
        "benchmark_version": V2_BENCHMARK_VERSION,
        "benchmark_role": V2_ROLE,
        "run_kind": "model_free_protocol_fixture",
        "manifest_digest": manifest["benchmark_digest"],
        "route_matrix_digest": manifest["route_matrix_digest"],
        "one_shot_identity": _one_shot_identity(manifest),
        "calibrations": fixture["calibrations"],
        "fixture": fixture["routes"],
        "v2_quality": "not_run",
        "selection": "not_run",
        "production_enablement": "not_run",
    }
    report["report_digest"] = sha256_text(canonical_json(report))
    return report


def _read_json(path):
    try:
        with open(path, encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise BenchmarkProtocolError("invalid artifact %s" % path) from error


def _verify_artifact_boundary(artifact_dir):
    artifact_dir = Path(artifact_dir)
    for path in artifact_dir.iterdir():
        if path.name not in ARTIFACT_FILENAMES or not path.is_file():
            raise BenchmarkProtocolError(
                "unexpected file in v2 artifact boundary: %s" % path)


def verify_artifact_privacy(artifact_dir):
    """Scan every local artifact in the declared boundary for live markers."""
    artifact_dir = Path(artifact_dir)
    _verify_artifact_boundary(artifact_dir)
    for path in sorted(artifact_dir.rglob("*")):
        if not path.is_file():
            continue
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as error:
            raise BenchmarkProtocolError(
                "cannot inspect privacy artifact %s" % path) from error
        for marker in PRIVACY_MARKERS:
            if marker in content:
                raise BenchmarkProtocolError(
                    "privacy marker %r found in %s" % (marker, path))
    return True


def _write_exclusive(path, content):
    try:
        with open(path, "x", encoding="utf-8") as handle:
            handle.write(content)
    except FileExistsError as error:
        raise BenchmarkProtocolError("artifact already exists: %s" % path) from error


def freeze_inputs(artifact_dir):
    """Create the immutable local boundary before any one-shot report."""
    artifact_dir = Path(artifact_dir)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    if any(artifact_dir.iterdir()):
        raise BenchmarkProtocolError("v2 artifact boundary must start empty")
    manifest = benchmark_manifest_v2()
    _write_exclusive(artifact_dir / "semantic_benchmark_v2_manifest.json",
                     canonical_json(manifest) + "\n")
    _write_exclusive(artifact_dir / "semantic_benchmark_v2_review.md",
                     render_review_table())
    marker = {
        "state": "frozen",
        "contract": CONTRACT_ID,
        "benchmark_version": V2_BENCHMARK_VERSION,
        "manifest_digest": manifest["benchmark_digest"],
        "route_matrix_digest": manifest["route_matrix_digest"],
    }
    _write_exclusive(artifact_dir / "semantic_benchmark_v2.frozen",
                     canonical_json(marker) + "\n")
    return manifest


def verify_frozen_inputs(artifact_dir):
    artifact_dir = Path(artifact_dir)
    manifest_path = artifact_dir / "semantic_benchmark_v2_manifest.json"
    marker_path = artifact_dir / "semantic_benchmark_v2.frozen"
    if not manifest_path.is_file() or not marker_path.is_file():
        raise BenchmarkProtocolError("v2 inputs were not frozen before report")
    _verify_artifact_boundary(artifact_dir)
    verify_artifact_privacy(artifact_dir)
    manifest = _read_json(manifest_path)
    marker = _read_json(marker_path)
    expected = benchmark_manifest_v2()
    if canonical_json(manifest) != canonical_json(expected):
        raise BenchmarkProtocolError("frozen v2 manifest drifted")
    digest = manifest.get("benchmark_digest")
    if digest != canonical_manifest_digest(manifest):
        raise BenchmarkProtocolError("v2 manifest digest mismatch")
    if marker != {
            "state": "frozen",
            "contract": CONTRACT_ID,
            "benchmark_version": V2_BENCHMARK_VERSION,
            "manifest_digest": manifest["benchmark_digest"],
            "route_matrix_digest": manifest["route_matrix_digest"],
    }:
        raise BenchmarkProtocolError("v2 frozen marker mismatch")
    validate_route_matrix(manifest["route_matrix"])
    return manifest


def _assert_desensitized_report(report):
    serialized = json.dumps(report, ensure_ascii=False, sort_keys=True)
    forbidden_keys = (
        "query_preceding_text", "recorded_preceding_text",
        "source_texts", "candidate_text", "final_selection_text",
    )
    if any('"%s"' % key in serialized for key in forbidden_keys):
        raise BenchmarkProtocolError("report contains raw benchmark payload")
    for case in benchmark_cases_v2():
        if case.source_query_text in serialized or \
                case.source_recorded_text in serialized:
            raise BenchmarkProtocolError("report contains raw case text")


def _verify_report_calibrations(manifest, report):
    expected_routes = {route["route_id"] for route in manifest["route_matrix"]}
    calibrations = report.get("calibrations")
    if not isinstance(calibrations, dict) or set(calibrations) != expected_routes:
        raise BenchmarkProtocolError("report calibration route set drifted")
    for route in manifest["route_matrix"]:
        route_id = route["route_id"]
        record = calibrations[route_id]
        observations = record.get("observations")
        actual = record.get("calibration")
        if not isinstance(observations, list) or not isinstance(actual, dict):
            raise BenchmarkProtocolError("report calibration is incomplete")
        expected = calibrate_v1_q95(observations)
        if actual != expected:
            raise BenchmarkProtocolError(
                "route %s does not use v1-only Q95 calibration" % route_id)


def accept_one_shot_report(artifact_dir, report):
    """Verify and record exactly one report for the frozen route identity."""
    artifact_dir = Path(artifact_dir)
    manifest = verify_frozen_inputs(artifact_dir)
    if not isinstance(report, dict):
        raise BenchmarkProtocolError("one-shot report must be an object")
    if report.get("contract") != CONTRACT_ID or \
            report.get("benchmark_version") != V2_BENCHMARK_VERSION or \
            report.get("benchmark_role") != V2_ROLE:
        raise BenchmarkProtocolError("report contract/version mismatch")
    if report.get("run_kind") != "model_free_protocol_fixture":
        raise BenchmarkProtocolError("report run kind is not the model-free fixture")
    expected_report_keys = {
        "contract", "benchmark_version", "benchmark_role", "run_kind",
        "manifest_digest", "route_matrix_digest", "one_shot_identity",
        "calibrations", "fixture", "v2_quality", "selection",
        "production_enablement", "report_digest",
    }
    if set(report) != expected_report_keys:
        raise BenchmarkProtocolError("report schema drifted")
    if report.get("manifest_digest") != manifest["benchmark_digest"] or \
            report.get("route_matrix_digest") != manifest["route_matrix_digest"]:
        raise BenchmarkProtocolError("report manifest or route digest mismatch")
    if report.get("one_shot_identity") != _one_shot_identity(manifest):
        raise BenchmarkProtocolError("report one-shot identity mismatch")
    report_digest = report.get("report_digest")
    without_digest = {
        key: value for key, value in report.items() if key != "report_digest"
    }
    if report_digest != sha256_text(canonical_json(without_digest)):
        raise BenchmarkProtocolError("report digest mismatch")
    if report.get("v2_quality") != "not_run":
        raise BenchmarkProtocolError("v2 quality results are out of scope")
    if report.get("selection") != "not_run" or \
            report.get("production_enablement") != "not_run":
        raise BenchmarkProtocolError("report enables deferred product behavior")
    _assert_desensitized_report(report)
    _verify_report_calibrations(manifest, report)
    expected_fixture = _run_fixture_gate(manifest)
    if report.get("calibrations") != expected_fixture["calibrations"]:
        raise BenchmarkProtocolError("report fixture calibration drifted")
    expected_routes = {route["route_id"] for route in manifest["route_matrix"]}
    fixture = report.get("fixture")
    if not isinstance(fixture, dict) or set(fixture) != expected_routes:
        raise BenchmarkProtocolError("fixture route set drifted")
    if fixture != expected_fixture["routes"]:
        raise BenchmarkProtocolError("model-free fixture metrics drifted")
    if not all(result.get("gate_pass") for result in fixture.values()):
        raise BenchmarkProtocolError("model-free protocol fixture failed")
    receipt_path = artifact_dir / "semantic_benchmark_v2.accepted"
    report_path = artifact_dir / "semantic_benchmark_v2_report.json"
    receipt = {
        "state": "accepted",
        "one_shot_identity": _one_shot_identity(manifest),
        "route_matrix_digest": manifest["route_matrix_digest"],
        "report_digest": report_digest,
    }
    _write_exclusive(receipt_path, canonical_json(receipt) + "\n")
    try:
        _write_exclusive(report_path, canonical_json(report) + "\n")
    except BenchmarkProtocolError:
        # The receipt intentionally remains as a fail-closed claim if a
        # concurrent or prior writer created the report path.
        raise
    return {"manifest": manifest, "report": report,
            "receipt_path": str(receipt_path),
            "report_path": str(report_path)}


def run_model_free_fixture(artifact_dir=None):
    if artifact_dir is None:
        artifact_dir = tempfile.mkdtemp(prefix="semantic-benchmark-v2-")
    freeze_inputs(artifact_dir)
    report = build_fixture_report(artifact_dir)
    return accept_one_shot_report(artifact_dir, report)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", action="store_true",
                        help="run the model-free v2 protocol fixture")
    parser.add_argument("--artifact-dir", default=None,
                        help="temporary local artifact boundary")
    args = parser.parse_args()
    if not args.fixture:
        parser.error("--fixture is required; real v2 routes are deferred")
    result = run_model_free_fixture(args.artifact_dir)
    print(json.dumps({
        "contract": result["report"]["contract"],
        "benchmark_digest": result["manifest"]["benchmark_digest"],
        "route_matrix_digest": result["manifest"]["route_matrix_digest"],
        "one_shot_identity": result["report"]["one_shot_identity"],
        "v2_quality": result["report"]["v2_quality"],
        "report_path": result["report_path"],
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
