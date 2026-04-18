from __future__ import annotations

from llm_service import LLMService
from schema import ProcessedData, RawData


class DecisionEngine:
    def __init__(self, llm_service: LLMService) -> None:
        self.llm = llm_service

    async def process(self, raw_data: RawData) -> ProcessedData:
        opinions = await self.llm.extract_opinions(raw_data)
        aggregated = await self.llm.aggregate(opinions, raw_data.query)
        return ProcessedData(
            decision_topic=raw_data.query,
            opinions=opinions,
            aggregated=aggregated,
        )
