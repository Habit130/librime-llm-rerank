#!/usr/bin/env python3
"""Throwaway semantic-neighbor comparison logic for squirrel#33.

Question: which Qwen3-0.6B-Base layer, token position, pooling, normalization,
and exact-vs-reused tokenization produce useful neighbors for a 64-character
preceding-text window? This module deliberately uses a small hand-authored
Chinese corpus. It is an inspection aid, not production retrieval code.
"""

from dataclasses import dataclass
from difflib import SequenceMatcher
import statistics
import time
from typing import Optional

import mlx.core as mx
import numpy as np
from mlx_lm.models.base import create_attention_mask
from mlx_lm.models.cache import KVCache, make_prompt_cache
from mlx_lm.utils import load


MODEL_PATH = "/Users/habit/Models/Qwen/Qwen3-0.6B-Base"
CONTEXT_WINDOW = 64
TAIL_CHARS = 4
LAYERS = (7, 14, 21, 28)


@dataclass(frozen=True)
class MemoryEvent:
    event_id: str
    group: str
    context: str
    selected: str
    intent: str


@dataclass(frozen=True)
class Query:
    query_id: str
    group: str
    context: str
    expected: str
    intent: str


@dataclass(frozen=True)
class Representation:
    name: str
    vector_key: Optional[str]
    metric: str
    description: str
    pair_conditioned: bool = False


@dataclass(frozen=True)
class Metrics:
    top1: float
    mrr: float
    mean_margin: float
    median_ms: float


GROUPS = {
    "gongji": ("攻击", "公鸡"),
    "quanli": ("权利", "权力"),
    "shijian": ("时间", "事件"),
    "zhidu": ("制度", "只读"),
    "jilu": ("记录", "纪律"),
    "fayan": ("发言", "发炎"),
    "shishi": ("实施", "事实"),
}


def _events(group, selected, intent, contexts):
    return [
        MemoryEvent(
            event_id=f"m-{group}-{selected}-{index}",
            group=group,
            context=context,
            selected=selected,
            intent=intent,
        )
        for index, context in enumerate(contexts, 1)
    ]


MEMORY_EVENTS = (
    _events(
        "gongji",
        "攻击",
        "进攻",
        ("指挥官下令向敌军发起", "部队准备对目标展开", "黑客开始对服务器发动", "这座农场昨夜遭到野兽"),
    )
    + _events(
        "gongji",
        "公鸡",
        "雄鸡",
        ("天刚亮院子里的", "农场养了一只昂首挺胸的", "每天清晨负责打鸣的是那只", "孩子指着鸡舍里红冠子的"),
    )
    + _events(
        "quanli",
        "权利",
        "法定权益",
        ("法律保障每位公民的", "劳动者依法享有休息的", "消费者拥有退换商品的", "宪法保护选民参与政治的"),
    )
    + _events(
        "quanli",
        "权力",
        "支配能力",
        ("总统掌握国家最高行政", "董事会拥有任免高管的", "这个职位赋予他很大的", "法律必须约束政府滥用"),
    )
    + _events(
        "shijian",
        "时间",
        "时刻时长",
        ("会议安排在什么", "请确认列车到达", "项目还需要更多", "我们约好下次见面的"),
    )
    + _events(
        "shijian",
        "事件",
        "发生事项",
        ("系统记录了一次异常", "警方正在调查这起", "日志里出现了安全", "记者持续跟进突发"),
    )
    + _events(
        "zhidu",
        "制度",
        "规则体系",
        ("公司建立新的考勤", "学校完善学生管理", "改革现有审批", "部门严格执行保密"),
    )
    + _events(
        "zhidu",
        "只读",
        "访问权限",
        ("文件被设置成", "磁盘以", "配置目录当前是", "这个账户只有"),
    )
    + _events(
        "jilu",
        "记录",
        "留存信息",
        ("系统保存每次操作", "档案中缺少相关", "请查看昨天的聊天", "数据库写入审计"),
    )
    + _events(
        "jilu",
        "纪律",
        "行为规范",
        ("军人必须遵守", "课堂上要维持", "组织成员应严守", "比赛委员会处理违反"),
    )
    + _events(
        "fayan",
        "发言",
        "公开讲话",
        ("主持人邀请专家上台", "代表将在会上公开", "轮到学生依次", "议员拒绝继续"),
    )
    + _events(
        "fayan",
        "发炎",
        "身体炎症",
        ("伤口感染后开始", "牙龈红肿明显", "手指破皮处有些", "医生说扁桃体已经"),
    )
    + _events(
        "shishi",
        "实施",
        "执行方案",
        ("计划将在下个月开始", "新政策由各部门负责", "工程方案已经进入", "团队准备按步骤"),
    )
    + _events(
        "shishi",
        "事实",
        "客观情况",
        ("证据证明这就是", "他不得不承认这个", "调查揭示一个重要", "报道歪曲了基本"),
    )
)


QUERIES = (
    Query("q-attack-order", "gongji", "司令要求部队立即展开", "攻击", "进攻"),
    Query("q-rooster-dawn", "gongji", "农场主听见清晨打鸣的", "公鸡", "雄鸡"),
    Query("q-attack-coop", "gongji", "鸡舍昨晚遭到狐狸", "攻击", "进攻"),
    Query("q-rooster-child", "gongji", "孩子在农场追着那只", "公鸡", "雄鸡"),
    Query("q-right-consumer", "quanli", "新规不得侵犯消费者的", "权利", "法定权益"),
    Query("q-power-president", "quanli", "新宪法扩大了总统的", "权力", "支配能力"),
    Query("q-right-law", "quanli", "这项规定不得剥夺用户申诉的", "权利", "法定权益"),
    Query("q-power-law", "quanli", "这项规定并没有赋予平台随意封号的", "权力", "支配能力"),
    Query("q-time-flight", "shijian", "请告诉我航班起飞的", "时间", "时刻时长"),
    Query("q-event-crash", "shijian", "日志捕获到一次崩溃", "事件", "发生事项"),
    Query("q-time-investigation", "shijian", "调查还需要很长一段", "时间", "时刻时长"),
    Query("q-event-three", "shijian", "系统在三点记录了一次异常", "事件", "发生事项"),
    Query("q-system-access", "zhidu", "管理员制定数据访问", "制度", "规则体系"),
    Query("q-readonly-partition", "zhidu", "挂载后整个分区变成", "只读", "访问权限"),
    Query("q-system-review", "zhidu", "团队准备调整绩效考核", "制度", "规则体系"),
    Query("q-readonly-document", "zhidu", "权限不足所以文档处于", "只读", "访问权限"),
    Query("q-record-log", "jilu", "服务端保留了完整访问", "记录", "留存信息"),
    Query("q-discipline-team", "jilu", "球队因违反赛场", "纪律", "行为规范"),
    Query("q-record-class", "jilu", "老师查看了学生的考勤", "记录", "留存信息"),
    Query("q-discipline-file", "jilu", "档案显示他曾受到违反", "纪律", "行为规范"),
    Query("q-speech-chair", "fayan", "主席请下一位代表", "发言", "公开讲话"),
    Query("q-inflammation-wound", "fayan", "伤口周围红肿疑似", "发炎", "身体炎症"),
    Query("q-speech-doctor", "fayan", "医生在会议上作总结", "发言", "公开讲话"),
    Query("q-inflammation-throat", "fayan", "他嗓子感染已经", "发炎", "身体炎症"),
    Query("q-implement-reform", "shishi", "改革方案明年正式", "实施", "执行方案"),
    Query("q-fact-audit", "shishi", "审计材料确认这一", "事实", "客观情况"),
    Query("q-fact-data", "shishi", "数据无法改变客观", "事实", "客观情况"),
    Query(
        "q-implement-boundary",
        "shishi",
        "在完成需求评审架构设计接口联调压力测试和上线审批之后团队终于决定从下周一开始按照既定的迁移方案分批",
        "实施",
        "执行方案",
    ),
)


REPRESENTATIONS = (
    Representation("lexical-char", None, "lexical", "字符 2/3-gram 与编辑相似度基线"),
    Representation("exact-L07-last", "exact_l07_last", "cosine", "精确 64 字；第 7 层；末 token；L2/cosine"),
    Representation("exact-L14-last", "exact_l14_last", "cosine", "精确 64 字；第 14 层；末 token；L2/cosine"),
    Representation("exact-L21-last", "exact_l21_last", "cosine", "精确 64 字；第 21 层；末 token；L2/cosine"),
    Representation("exact-L28-last", "exact_l28_last", "cosine", "精确 64 字；最终层；末 token；L2/cosine"),
    Representation(
        "prefix-L21-last",
        "prefix_l21_last",
        "cosine",
        "复用现有 prefix forward；省略最新 4 字；第 21 层末 token；零额外 forward",
    ),
    Representation(
        "prefix-L28-last",
        "prefix_l28_last",
        "cosine",
        "复用现有 prefix forward；省略最新 4 字；最终层末 token；零额外 forward",
    ),
    Representation("exact-L28-last-centered", "exact_l28_last", "centered", "最终层末 token；按记忆语料中心化后 L2/cosine"),
    Representation("exact-L28-last-dot", "exact_l28_last", "dot", "最终层末 token；不归一化 dot product"),
    Representation("exact-L14-mean", "exact_l14_mean", "cosine", "精确 64 字；第 14 层；masked mean；L2/cosine"),
    Representation("exact-L21-mean", "exact_l21_mean", "cosine", "精确 64 字；第 21 层；masked mean；L2/cosine"),
    Representation("exact-L28-mean", "exact_l28_mean", "cosine", "精确 64 字；最终层；masked mean；L2/cosine"),
    Representation("exact-EOS-L28-last", "eos_l28_last", "cosine", "精确 64 字后追加 EOS；最终层末 token；L2/cosine"),
    Representation("split-L28-last", "split_l28_last", "cosine", "复用打分 seam：prefix 与末 4 字分词；最终层末 token"),
    Representation(
        "pair-L28-last",
        "pair_l28_last",
        "cosine",
        "候选条件化：上文+候选；每个候选分别检索；最终层末 token",
        pair_conditioned=True,
    ),
)


class HiddenStateExtractor:
    def __init__(self, model_path=MODEL_PATH):
        self.model, self.tokenizer = load(model_path)
        mx.eval(self.model.parameters())
        self.timings = {
            "exact": [],
            "eos": [],
            "split_total": [],
            "split_tail": [],
            "pair": [],
        }
        self.seam_changed = []
        self._forward_exact("原型热身")

    def _ids(self, text):
        return self.tokenizer.encode(text, add_special_tokens=False)

    def _forward(self, token_ids, cache=None):
        if not token_ids:
            token_ids = [self.tokenizer.eos_token_id]
        h = self.model.model.embed_tokens(mx.array([token_ids]))
        layer_cache = cache if cache is not None else [None] * len(self.model.model.layers)
        mask = create_attention_mask(h, layer_cache[0])
        snapshots = {}
        for layer_number, (layer, current_cache) in enumerate(
            zip(self.model.model.layers, layer_cache), 1
        ):
            h = layer(h, mask, current_cache)
            if layer_number in LAYERS:
                # Keep layer comparisons on one scale; representation_id must
                # record that intermediate states use Qwen's final RMSNorm.
                normalized = self.model.model.norm(h).astype(mx.float32)
                snapshots[f"l{layer_number:02d}_last"] = normalized[0, -1]
                if layer_number in (14, 21, 28):
                    snapshots[f"l{layer_number:02d}_mean"] = mx.mean(
                        normalized[0], axis=0
                    )
        mx.eval(*snapshots.values())
        return {key: np.asarray(value) for key, value in snapshots.items()}

    def _forward_exact(self, text, append_eos=False):
        token_ids = self._ids(text[-CONTEXT_WINDOW:])
        if append_eos:
            token_ids.append(self.tokenizer.eos_token_id)
        return self._forward(token_ids)

    def exact(self, context):
        start = time.perf_counter()
        vectors = self._forward_exact(context)
        self.timings["exact"].append((time.perf_counter() - start) * 1000)
        return {f"exact_{key}": value for key, value in vectors.items()}

    def eos(self, context):
        start = time.perf_counter()
        vectors = self._forward_exact(context, append_eos=True)
        self.timings["eos"].append((time.perf_counter() - start) * 1000)
        return {"eos_l28_last": vectors["l28_last"]}

    def split(self, context):
        context = context[-CONTEXT_WINDOW:]
        prefix_text = context[:-TAIL_CHARS] if len(context) > TAIL_CHARS else ""
        tail_text = context[-TAIL_CHARS:] if len(context) > TAIL_CHARS else context
        prefix_ids = self._ids(prefix_text) if prefix_text else []
        tail_ids = self._ids(tail_text)
        exact_ids = self._ids(context)
        self.seam_changed.append(exact_ids != prefix_ids + tail_ids)

        total_start = time.perf_counter()
        cache = make_prompt_cache(self.model)
        if prefix_ids:
            prefix_vectors = self._forward(prefix_ids, cache)
            cache_arrays = [array for item in cache for array in (item.keys, item.values)]
            mx.eval(*cache_arrays)
        else:
            prefix_vectors = None
        tail_start = time.perf_counter()
        vectors = self._forward(tail_ids, cache)
        self.timings["split_tail"].append((time.perf_counter() - tail_start) * 1000)
        self.timings["split_total"].append((time.perf_counter() - total_start) * 1000)
        if prefix_vectors is None:
            prefix_vectors = vectors
        return {
            "prefix_l21_last": prefix_vectors["l21_last"],
            "prefix_l28_last": prefix_vectors["l28_last"],
            "split_l28_last": vectors["l28_last"],
        }

    def pair(self, context, candidate):
        start = time.perf_counter()
        vectors = self._forward_exact(context[-CONTEXT_WINDOW:] + candidate)
        self.timings["pair"].append((time.perf_counter() - start) * 1000)
        return {"pair_l28_last": vectors["l28_last"]}

    def benchmark_integrated_context_row(self, rounds=12):
        """Measure adding one context row to the existing N=32 suffix batch."""
        context = "在完成需求评审架构设计接口联调之后团队决定开始实施迁移方案"
        candidates = (
            "实施",
            "事实",
            "攻击",
            "公鸡",
            "权利",
            "权力",
            "记录",
            "纪律",
        ) * 4
        context = context[-CONTEXT_WINDOW:]
        prefix_text = context[:-TAIL_CHARS]
        tail_text = context[-TAIL_CHARS:]
        prefix_ids = self._ids(prefix_text)
        candidate_ids = [self._ids(tail_text + candidate) for candidate in candidates]
        context_ids = self._ids(tail_text)
        max_length = max(max(map(len, candidate_ids)), len(context_ids))

        def padded(rows):
            pad_id = self.tokenizer.pad_token_id or self.tokenizer.eos_token_id
            return mx.array([row + [pad_id] * (max_length - len(row)) for row in rows])

        baseline_suffix = padded(candidate_ids)
        integrated_suffix = padded(candidate_ids + [context_ids])
        prefix_cache = make_prompt_cache(self.model)
        prefix_logits = self.model(mx.array([prefix_ids]), prefix_cache)
        cache_arrays = [
            array for item in prefix_cache for array in (item.keys, item.values)
        ]
        mx.eval(prefix_logits, *cache_arrays)

        def expand_cache(batch_size):
            expanded = []
            for item in prefix_cache:
                valid = item.offset
                keys = item.keys[..., :valid, :]
                values = item.values[..., :valid, :]
                full_keys = mx.concatenate(
                    [
                        mx.broadcast_to(
                            keys,
                            (batch_size, keys.shape[1], valid, keys.shape[3]),
                        ),
                        mx.zeros(
                            (batch_size, keys.shape[1], max_length, keys.shape[3]),
                            dtype=keys.dtype,
                        ),
                    ],
                    axis=2,
                )
                full_values = mx.concatenate(
                    [
                        mx.broadcast_to(
                            values,
                            (batch_size, values.shape[1], valid, values.shape[3]),
                        ),
                        mx.zeros(
                            (
                                batch_size,
                                values.shape[1],
                                max_length,
                                values.shape[3],
                            ),
                            dtype=values.dtype,
                        ),
                    ],
                    axis=2,
                )
                cache = KVCache()
                cache.keys = full_keys
                cache.values = full_values
                cache.offset = valid
                expanded.append(cache)
            return expanded

        def baseline():
            cache = expand_cache(len(candidates))
            logits = self.model(baseline_suffix, cache)
            mx.eval(logits)

        def final_integrated():
            cache = expand_cache(len(candidates) + 1)
            hidden = self.model.model(integrated_suffix, cache)
            context_vector = hidden[-1, len(context_ids) - 1]
            if self.model.args.tie_word_embeddings:
                logits = self.model.model.embed_tokens.as_linear(hidden[:-1])
            else:
                logits = self.model.lm_head(hidden[:-1])
            mx.eval(logits, context_vector)

        def l21_integrated():
            cache = expand_cache(len(candidates) + 1)
            h = self.model.model.embed_tokens(integrated_suffix)
            mask = create_attention_mask(h, cache[0])
            context_vector = None
            for layer_number, (layer, current_cache) in enumerate(
                zip(self.model.model.layers, cache), 1
            ):
                h = layer(h, mask, current_cache)
                if layer_number == 21:
                    context_hidden = h[-1:, len(context_ids) - 1 : len(context_ids)]
                    context_vector = self.model.model.norm(context_hidden)[0, 0]
            hidden = self.model.model.norm(h)
            if self.model.args.tie_word_embeddings:
                logits = self.model.model.embed_tokens.as_linear(hidden[:-1])
            else:
                logits = self.model.lm_head(hidden[:-1])
            mx.eval(logits, context_vector)

        baseline()
        final_integrated()
        l21_integrated()
        baseline_times = []
        final_times = []
        l21_times = []
        for index in range(rounds):
            actions = (baseline, final_integrated, l21_integrated)
            offset = index % len(actions)
            actions = actions[offset:] + actions[:offset]
            for action in actions:
                start = time.perf_counter()
                action()
                elapsed = (time.perf_counter() - start) * 1000
                if action is baseline:
                    baseline_times.append(elapsed)
                elif action is final_integrated:
                    final_times.append(elapsed)
                else:
                    l21_times.append(elapsed)
        baseline_median = statistics.median(baseline_times)
        final_median = statistics.median(final_times)
        l21_median = statistics.median(l21_times)
        return {
            "baseline_ms": baseline_median,
            "final_ms": final_median,
            "final_delta_ms": final_median - baseline_median,
            "l21_ms": l21_median,
            "l21_delta_ms": l21_median - baseline_median,
        }


class PrototypeResults:
    def __init__(self, extractor):
        self.extractor = extractor
        self.memory_vectors = {}
        self.query_vectors = {}
        self.query_pair_vectors = {}
        self.centroids = {}
        self.hot_path = None

    def build(self, progress=None):
        total = len(MEMORY_EVENTS) + len(QUERIES)
        completed = 0
        for event in MEMORY_EVENTS:
            vectors = {}
            vectors.update(self.extractor.exact(event.context))
            vectors.update(self.extractor.eos(event.context))
            vectors.update(self.extractor.split(event.context))
            vectors.update(self.extractor.pair(event.context, event.selected))
            self.memory_vectors[event.event_id] = vectors
            completed += 1
            if progress:
                progress(completed, total)

        for query in QUERIES:
            vectors = {}
            vectors.update(self.extractor.exact(query.context))
            vectors.update(self.extractor.eos(query.context))
            vectors.update(self.extractor.split(query.context))
            self.query_vectors[query.query_id] = vectors
            for candidate in GROUPS[query.group]:
                pair_vectors = self.extractor.pair(query.context, candidate)
                self.query_pair_vectors[(query.query_id, candidate)] = pair_vectors
            completed += 1
            if progress:
                progress(completed, total)

        for representation in REPRESENTATIONS:
            if representation.vector_key is None:
                continue
            vectors = [
                self.memory_vectors[event.event_id][representation.vector_key]
                for event in MEMORY_EVENTS
            ]
            self.centroids[representation.name] = np.mean(vectors, axis=0)
        self.hot_path = self.extractor.benchmark_integrated_context_row()

    def _vector(self, item, representation, candidate=None):
        if isinstance(item, MemoryEvent):
            return self.memory_vectors[item.event_id][representation.vector_key]
        if representation.pair_conditioned:
            return self.query_pair_vectors[(item.query_id, candidate)][
                representation.vector_key
            ]
        return self.query_vectors[item.query_id][representation.vector_key]

    def similarity(self, query, event, representation, candidate=None):
        if representation.metric == "lexical":
            return lexical_similarity(query.context, event.context)
        query_vector = self._vector(query, representation, candidate)
        event_vector = self._vector(event, representation)
        if representation.metric == "centered":
            center = self.centroids[representation.name]
            query_vector = query_vector - center
            event_vector = event_vector - center
        if representation.metric == "dot":
            return float(np.dot(query_vector, event_vector) / query_vector.size)
        return cosine(query_vector, event_vector)

    def neighbors(self, query, representation, group_only=False, candidate=None):
        if representation.pair_conditioned and candidate is None:
            candidate = query.expected
        events = MEMORY_EVENTS
        if group_only:
            events = [event for event in events if event.group == query.group]
        ranked = [
            (
                event,
                self.similarity(query, event, representation, candidate=candidate),
            )
            for event in events
        ]
        return sorted(ranked, key=lambda item: item[1], reverse=True)

    def metrics(self, representation):
        successes = 0
        reciprocal_ranks = []
        margins = []
        for query in QUERIES:
            if representation.pair_conditioned:
                candidate_scores = {}
                for candidate in GROUPS[query.group]:
                    matching = [
                        score
                        for event, score in self.neighbors(
                            query,
                            representation,
                            group_only=True,
                            candidate=candidate,
                        )
                        if event.selected == candidate
                    ]
                    candidate_scores[candidate] = max(matching)
                ranked_candidates = sorted(
                    candidate_scores, key=candidate_scores.get, reverse=True
                )
                expected_rank = ranked_candidates.index(query.expected) + 1
                wrong_best = max(
                    score
                    for candidate, score in candidate_scores.items()
                    if candidate != query.expected
                )
                margin = candidate_scores[query.expected] - wrong_best
            else:
                ranked = self.neighbors(query, representation, group_only=True)
                expected_rank = next(
                    index
                    for index, (event, _) in enumerate(ranked, 1)
                    if event.selected == query.expected
                )
                positive_best = max(
                    score for event, score in ranked if event.selected == query.expected
                )
                wrong_best = max(
                    score for event, score in ranked if event.selected != query.expected
                )
                margin = positive_best - wrong_best
            successes += expected_rank == 1
            reciprocal_ranks.append(1.0 / expected_rank)
            margins.append(margin)
        return Metrics(
            top1=successes / len(QUERIES),
            mrr=statistics.mean(reciprocal_ranks),
            mean_margin=statistics.mean(margins),
            median_ms=self.median_latency(representation),
        )

    def median_latency(self, representation):
        if representation.metric == "lexical":
            return 0.0
        if representation.vector_key.startswith("prefix_"):
            return 0.0
        if representation.vector_key.startswith("eos_"):
            timing = "eos"
        elif representation.vector_key.startswith("split_"):
            timing = "split_tail"
        elif representation.vector_key.startswith("pair_"):
            timing = "pair"
        else:
            timing = "exact"
        return statistics.median(self.extractor.timings[timing])

    def split_fidelity(self):
        similarities = []
        for event in MEMORY_EVENTS:
            vectors = self.memory_vectors[event.event_id]
            similarities.append(
                cosine(vectors["exact_l28_last"], vectors["split_l28_last"])
            )
        for query in QUERIES:
            vectors = self.query_vectors[query.query_id]
            similarities.append(
                cosine(vectors["exact_l28_last"], vectors["split_l28_last"])
            )
        ordered = sorted(similarities)
        fifth_index = max(0, int(len(ordered) * 0.05) - 1)
        return {
            "median_cosine": statistics.median(similarities),
            "p05_cosine": ordered[fifth_index],
            "seam_changed_rate": statistics.mean(self.extractor.seam_changed),
            "median_total_ms": statistics.median(
                self.extractor.timings["split_total"]
            ),
            "median_tail_ms": statistics.median(
                self.extractor.timings["split_tail"]
            ),
        }


def cosine(left, right):
    denominator = np.linalg.norm(left) * np.linalg.norm(right)
    if denominator == 0:
        return 0.0
    return float(np.dot(left, right) / denominator)


def lexical_similarity(left, right):
    def ngrams(text):
        grams = set(text)
        for size in (2, 3):
            grams.update(text[index : index + size] for index in range(len(text) - size + 1))
        return grams

    left_grams = ngrams(left)
    right_grams = ngrams(right)
    union = left_grams | right_grams
    jaccard = len(left_grams & right_grams) / len(union) if union else 0.0
    edit = SequenceMatcher(None, left, right).ratio()
    return 0.7 * jaccard + 0.3 * edit
