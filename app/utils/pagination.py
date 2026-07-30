"""Shared limit/offset pagination for every list endpoint."""


def paginate(query, page: int = 1, page_size: int = 20, max_page_size: int = 100):
    page = max(1, page)
    page_size = min(max(1, page_size), max_page_size)
    total = query.count()
    items = query.offset((page - 1) * page_size).limit(page_size).all()
    pages = (total + page_size - 1) // page_size if total else 1
    return {
        "items": items,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": pages,
    }
