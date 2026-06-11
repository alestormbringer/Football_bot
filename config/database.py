from supabase import create_client, Client
from config.settings import SUPABASE_URL, SUPABASE_KEY

_client: Client | None = None


def get_client() -> Client:
    """Restituisce un client Supabase singleton."""
    global _client
    if _client is None:
        _client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return _client
