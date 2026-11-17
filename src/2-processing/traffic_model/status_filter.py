"""Filtro de peticiones por código de respuesta HTTP."""


def successful_rows(df):
    """Filas que la aplicación aceptó (2xx) y filas sin código de respuesta.

    Si el log no tiene la columna `status`, o la tiene vacía, lo devuelve tal cual.
    """
    if df is None or df.empty or "status" not in df.columns or df["status"].isna().all():
        return df
    status = df["status"]
    return df[status.isna() | ((status >= 200) & (status < 300))]
