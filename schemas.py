from pydantic import BaseModel, Field
from typing import List, Optional
from datetime import datetime

class AnalysisBase(BaseModel):
    sentiment_score: float = Field(..., ge=-1.0, le=1.0)
    executive_synthesis: str = Field(..., max_length=300)
    critical_points: List[str]
    raw_json_file: str

class AnalysisCreate(AnalysisBase):
    pass

class Analysis(AnalysisBase):
    id: int
    subnet_id: int
    created_at: datetime

    class Config:
        from_attributes = True

class SubnetBase(BaseModel):
    name: str

class SubnetCreate(SubnetBase):
    pass

class Subnet(SubnetBase):
    id: int
    created_at: datetime
    analyses: List[Analysis] = []

    class Config:
        from_attributes = True
