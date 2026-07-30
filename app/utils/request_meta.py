"""Extract visitor metadata (IP, browser, OS, device) from a request."""
import hashlib

from fastapi import Request


def get_client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def parse_user_agent(ua: str) -> dict:
    ua_l = (ua or "").lower()

    if "edg/" in ua_l or "edge" in ua_l:
        browser = "Edge"
    elif "opr/" in ua_l or "opera" in ua_l:
        browser = "Opera"
    elif "samsungbrowser" in ua_l:
        browser = "Samsung Internet"
    elif "firefox" in ua_l:
        browser = "Firefox"
    elif "chrome" in ua_l or "crios" in ua_l:
        browser = "Chrome"
    elif "safari" in ua_l:
        browser = "Safari"
    elif ua_l:
        browser = "Other"
    else:
        browser = "Unknown"

    if "android" in ua_l:
        os_name = "Android"
    elif "iphone" in ua_l or "ipad" in ua_l or "ipod" in ua_l:
        os_name = "iOS"
    elif "windows" in ua_l:
        os_name = "Windows"
    elif "mac os" in ua_l or "macintosh" in ua_l:
        os_name = "macOS"
    elif "linux" in ua_l:
        os_name = "Linux"
    else:
        os_name = "Unknown"

    if "ipad" in ua_l or "tablet" in ua_l:
        device = "Tablet"
    elif "mobi" in ua_l or "android" in ua_l or "iphone" in ua_l:
        device = "Mobile"
    else:
        device = "Desktop"

    return {"browser": browser, "os": os_name, "device": device}


def visitor_fingerprint(ip: str, ua: str) -> str:
    """Stable anonymous visitor id (hash of IP + user agent)."""
    return hashlib.sha256(f"{ip}|{ua}".encode()).hexdigest()[:32]
