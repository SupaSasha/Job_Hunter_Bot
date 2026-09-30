from pydantic import BaseModel


class DigestMetrics(BaseModel):
    candidate_count: int = 0
    filter_rejected_count: int = 0
    accepted_count: int = 0
    score_0_49_count: int = 0
    score_50_59_count: int = 0
    score_60_69_count: int = 0
    score_70_79_count: int = 0
    score_80_89_count: int = 0
    score_90_100_count: int = 0
    below_threshold_count: int = 0
