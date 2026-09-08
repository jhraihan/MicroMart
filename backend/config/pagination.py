"""Page-number pagination per PRD §7.1: ?page=1&page_size=24."""
from rest_framework.pagination import PageNumberPagination as _PageNumberPagination


class PageNumberPagination(_PageNumberPagination):
    page_size = 24
    page_size_query_param = "page_size"
    max_page_size = 100
