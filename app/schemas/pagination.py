from pydantic import BaseModel


class Pagination(BaseModel):
    total: int
    limit: int
    offset: int
    has_more: bool
