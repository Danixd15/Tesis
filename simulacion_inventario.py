import math
import pandas as pd
from dataclasses import dataclass

@dataclass
class ParametrosInventario:
    initial_stock: int
    lead_time_months: int
    review_period_months: int
    ss_months: float
    q_fixed: int
    lot_size: int
    cost_order: float
    cost_holding_month: float
    cost_stockout: float

def obtener_parametros_producto(df_params: pd.DataFrame, producto_id: str) -> ParametrosInventario:
    """
    Busca el producto en la hoja Datos y extrae sus parámetros de inventario.
    """

    df = df_params.copy()

    # Normalizar columnas
    df.columns = [str(c).strip().lower() for c in df.columns]

    alias = {
        "grupo de demanda": "product_id",
        "producto": "product_id",
        "sku": "product_id",

        "lead_time_months": "lead_time_mo",
        "lead time months": "lead_time_mo",
        "lead time mo": "lead_time_mo",

        "review_period_months": "review_period",
        "review period": "review_period",

        "moq": "q_fixed",
        "moq estándar": "q_fixed",
        "moq estandar": "q_fixed",

        "cost_holding": "cost_holding_month",
        "cost_holding_r": "cost_holding_month",
        "costo_mantener": "cost_holding_month",

        "cost_stockout": "cost_stockout",
        "costo_quiebre": "cost_stockout",
    }

    df = df.rename(columns={c: alias.get(c, c) for c in df.columns})

    if "product_id" not in df.columns:
        raise ValueError("La hoja Datos debe tener una columna llamada product_id.")

    df["product_id_limpio"] = df["product_id"].astype(str).str.strip().str.upper()
    producto_limpio = str(producto_id).strip().upper()

    df_filtrado = df[df["product_id_limpio"] == producto_limpio]

    if df_filtrado.empty:
        raise ValueError(
            f"No se encontró el producto '{producto_id}' en la hoja Datos. "
            "Verifica que el product_id coincida exactamente entre las hojas Demanda y Datos."
        )

    fila = df_filtrado.iloc[0]

    def numero(columna, default=0):
        valor = pd.to_numeric(fila.get(columna, default), errors="coerce")
        if pd.isna(valor):
            return default
        return valor

    initial_stock = int(numero("initial_stock", 0))
    lead_time_months = int(math.ceil(numero("lead_time_mo", 1)))
    review_period_months = int(numero("review_period", 1))
    ss_months = float(numero("ss_months", 0))
    q_fixed = int(numero("q_fixed", 100))
    lot_size = int(numero("lot_size", 1))
    cost_order = float(numero("cost_order", 0))
    cost_holding_month = float(numero("cost_holding_month", 0))
    cost_stockout = float(numero("cost_stockout", 0))

    lead_time_months = max(1, lead_time_months)
    review_period_months = max(1, review_period_months)
    q_fixed = max(1, q_fixed)
    lot_size = max(1, lot_size)

    return ParametrosInventario(
        initial_stock=initial_stock,
        lead_time_months=lead_time_months,
        review_period_months=review_period_months,
        ss_months=ss_months,
        q_fixed=q_fixed,
        lot_size=lot_size,
        cost_order=cost_order,
        cost_holding_month=cost_holding_month,
        cost_stockout=cost_stockout,
    )
    
def redondear_lote(cantidad: float, lote: int) -> int:
    if cantidad <= 0:
        return 0
    lote = max(1, int(lote))
    return int(math.ceil(cantidad / lote) * lote)

def simular_producto(df_producto: pd.DataFrame, politica: str, p: ParametrosInventario) -> pd.DataFrame:
    df_producto = df_producto.sort_values("date").reset_index(drop=True).copy()
    stock_fisico = float(p.initial_stock)
    pipeline = {}
    resultados = []
    demanda_promedio_mensual = max(0.01, df_producto["demand_forecast"].mean())

    for t, fila in df_producto.iterrows():
        llegada = pipeline.pop(t, 0)
        stock_fisico += llegada
        demanda_durante_lead_time = demanda_promedio_mensual * p.lead_time_months
        stock_seguridad = demanda_promedio_mensual * p.ss_months
        punto_reorden = demanda_durante_lead_time + stock_seguridad
        nivel_objetivo = demanda_promedio_mensual * (
            p.lead_time_months + p.review_period_months + p.ss_months
        )
        posicion_inventario = stock_fisico + sum(pipeline.values())
        orden = 0
        if politica == "RS - revisión periódica":
            if t % p.review_period_months == 0:
                orden = max(0, nivel_objetivo - posicion_inventario)
        elif politica == "sS - punto de reorden y nivel máximo":
            if posicion_inventario <= punto_reorden:
                orden = max(0, nivel_objetivo - posicion_inventario)
        elif politica == "sQ - punto de reorden y cantidad fija":
            if posicion_inventario <= punto_reorden:
                orden = p.q_fixed

        orden = redondear_lote(orden, p.lot_size)
        if orden > 0:
            mes_llegada = t + p.lead_time_months
            pipeline[mes_llegada] = pipeline.get(mes_llegada, 0) + orden

        demanda_real = float(fila.get("demand_forecast", fila["demand_real"]))
        venta_real = min(stock_fisico, demanda_real)
        venta_perdida = max(0, demanda_real - stock_fisico)
        stock_fisico -= venta_real

        resultados.append(
            {
                "date": fila["date"],
                "product_id": fila["product_id"],
                "method_used": fila.get("method_used", ""),
                "demand_real": demanda_real,
                "demand_forecast": fila["demand_forecast"],
                "inventory_level": stock_fisico,
                "inventory_position": posicion_inventario,
                "order_placed": orden,
                "arrivals": llegada,
                "sales_real": venta_real,
                "sales_lost": venta_perdida,
                "reorder_point_s": punto_reorden,
                "target_level_S": nivel_objetivo,
                "is_stockout": int(venta_perdida > 0),
            }
        )
    return pd.DataFrame(resultados)

def calcular_kpis(df_sim: pd.DataFrame, p: ParametrosInventario) -> dict:
    demanda_total = df_sim["demand_real"].sum()
    ventas_perdidas = df_sim["sales_lost"].sum()
    ordenes = (df_sim["order_placed"] > 0).sum()
    inventario_promedio = df_sim["inventory_level"].mean()
    fill_rate = 1 - ventas_perdidas / demanda_total if demanda_total > 0 else 1
    costo_ordenar = ordenes * p.cost_order
    costo_mantener = df_sim["inventory_level"].sum() * p.cost_holding_month
    costo_quiebre = ventas_perdidas * p.cost_stockout
    costo_total = costo_ordenar + costo_mantener + costo_quiebre
    return {
        "fill_rate": fill_rate,
        "avg_inventory": inventario_promedio,
        "lost_sales_units": ventas_perdidas,
        "stockout_months": int(df_sim["is_stockout"].sum()),
        "orders": int(ordenes),
        "ordering_cost": costo_ordenar,
        "holding_cost": costo_mantener,
        "stockout_cost": costo_quiebre,
        "total_cost": costo_total,
    }

def optimizar_stock_seguridad(df_producto: pd.DataFrame, politica: str, p_base: ParametrosInventario, ss_max: int) -> pd.DataFrame:
    filas = []
    for ss in range(0, ss_max + 1):
        p = ParametrosInventario(
            initial_stock=p_base.initial_stock,
            lead_time_months=p_base.lead_time_months,
            review_period_months=p_base.review_period_months,
            ss_months=ss,
            q_fixed=p_base.q_fixed,
            lot_size=p_base.lot_size,
            cost_order=p_base.cost_order,
            cost_holding_month=p_base.cost_holding_month,
            cost_stockout=p_base.cost_stockout,
        )
        sim = simular_producto(df_producto, politica, p)
        kpis = calcular_kpis(sim, p)
        filas.append({"ss_months": ss, **kpis})
    return pd.DataFrame(filas)
