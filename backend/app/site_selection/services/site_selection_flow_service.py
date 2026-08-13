"""区域行为流向分析的业务编排边界。"""

from collections import defaultdict

from app.schemas.site_selection_config import CandidateArea
from app.site_selection.repositories import SiteSelectionFlowRepository
from app.site_selection.schemas import (
    AreaFlowResult,
    AreaTransition,
    SessionAreaSequence,
)

_OUTSIDE_AREA_ID = "outside_candidate_area"


class SiteSelectionFlowService:
    """通过注入的 Repository 获取流向结果，不承担数据访问职责。"""

    def __init__(self, repository: SiteSelectionFlowRepository) -> None:
        """注入流向数据访问依赖。"""
        self.repository = repository

    def analyze_area_flows(
        self,
        candidate_areas: list[CandidateArea],
    ) -> list[AreaFlowResult]:
        """依次编排 Session 序列、相邻迁移和区域流向聚合。"""
        session_sequences = self.prepare_session_area_sequences(candidate_areas)
        transitions = self.build_area_transitions(session_sequences)
        return self.aggregate_area_flows(transitions)

    def prepare_area_mapping(
        self,
        candidate_areas: list[CandidateArea],
    ) -> dict[str, str]:
        """获取 POI 归属行并转换为 venue_id 到 area_id 的映射。"""
        assignments = self.repository.get_poi_area_mapping(candidate_areas)
        return dict(assignments)

    def prepare_session_area_sequences(
        self,
        candidate_areas: list[CandidateArea],
    ) -> list[SessionAreaSequence]:
        """委托 Repository 获取有效 Session 的有序区域状态序列。"""
        return self.repository.get_session_area_sequences(candidate_areas)

    def build_area_transitions(
        self,
        session_sequences: list[SessionAreaSequence],
    ) -> list[AreaTransition]:
        """将每个 Session 的有序区域状态转换为相邻跨区域迁移事实。"""
        transitions: list[AreaTransition] = []
        for sequence in session_sequences:
            adjacent_pairs = zip(sequence.areas, sequence.areas[1:])
            for source_area, target_area in adjacent_pairs:
                if source_area == target_area:
                    continue
                if _OUTSIDE_AREA_ID in (source_area, target_area):
                    continue
                transitions.append(
                    AreaTransition(
                        source_area=source_area,
                        target_area=target_area,
                        session_id=sequence.session_id,
                        user_id=sequence.user_id,
                    )
                )
        return transitions

    def aggregate_area_flows(
        self,
        transitions: list[AreaTransition],
    ) -> list[AreaFlowResult]:
        """按有向区域对聚合迁移次数、去重用户和去重 Session。"""
        flow_counts: defaultdict[tuple[str, str], int] = defaultdict(int)
        users_by_pair: defaultdict[tuple[str, str], set[str]] = defaultdict(set)
        sessions_by_pair: defaultdict[tuple[str, str], set[str]] = defaultdict(set)

        for transition in transitions:
            area_pair = (transition.source_area, transition.target_area)
            flow_counts[area_pair] += 1
            users_by_pair[area_pair].add(transition.user_id)
            sessions_by_pair[area_pair].add(transition.session_id)

        results = [
            AreaFlowResult(
                source_area=source_area,
                target_area=target_area,
                flow_count=flow_count,
                unique_users=len(users_by_pair[area_pair]),
                unique_sessions=len(sessions_by_pair[area_pair]),
            )
            for area_pair, flow_count in flow_counts.items()
            for source_area, target_area in [area_pair]
        ]
        return sorted(
            results,
            key=lambda result: (
                -result.flow_count,
                result.source_area,
                result.target_area,
            ),
        )
