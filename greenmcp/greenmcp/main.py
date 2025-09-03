
from greenmcp.mcp_server.server import app # noqa: F401

# Uyarı notu:
# Bu dosyada sadece FastAPI uygulaması 'app' dışa aktarılmakta ve doğrudan kullanılmamaktadır.
# Ancak sunucu çalıştırılırken (örneğin: `uvicorn main:app`) bu nesneye ihtiyaç duyulur.
# Bu nedenle 'app' burada tanımlı kalmalıdır. Kullanılmıyor gibi görünse de kasıtlıdır.
# Ruff uyarısını bastırmak için: # noqa: F401