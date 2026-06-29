import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots

def grafico_forecast(df_producto: pd.DataFrame) -> go.Figure:
    metodo = df_producto["method_used"].iloc[0] if "method_used" in df_producto.columns else ""

    df_hist = df_producto[df_producto.get("tipo_periodo", "Histórico") == "Histórico"].copy()
    df_future = df_producto[df_producto.get("tipo_periodo", "Histórico") == "Pronóstico futuro"].copy()

    fig = go.Figure()
    
    # Línea histórica
    fig.add_trace(
        go.Scatter(
            x=df_hist["date"],
            y=df_hist["demand_real"],
            mode="lines+markers",
            name="Demanda real",
            line=dict(color="#1f77b4", width=2)
        )
    )
    
    # Línea de ajuste (entrenamiento)
    fig.add_trace(
        go.Scatter(
            x=df_hist["date"],
            y=df_hist["demand_forecast"],
            mode="lines+markers",
            name=f"Ajuste ({metodo})",
            line=dict(color="#ff7f0e", width=2, dash="dot")
        )
    )

    # Línea de pronóstico futuro
    if not df_future.empty:
        fig.add_trace(
            go.Scatter(
                x=df_future["date"],
                y=df_future["demand_forecast"],
                mode="lines+markers",
                name="Pronóstico futuro",
                line=dict(color="#2ca02c", width=3, dash="dash")
            )
        )

    # Ajustes de diseño para evitar choques visuales
    fig.update_layout(
        xaxis_title="Mes",
        yaxis_title="Unidades",
        hovermode="x unified",
        margin=dict(l=20, r=20, t=20, b=20), # Márgenes reducidos
        legend=dict(
            orientation="h",   # Leyenda horizontal
            yanchor="top",     # Anclada desde arriba
            y=-0.15,           # Posicionada DEBAJO del eje X (evita chocar con la gráfica)
            xanchor="center",  # Centrada horizontalmente
            x=0.5
        )
    )
    return fig


def grafico_inventario(df_sim: pd.DataFrame) -> go.Figure:
    fig = make_subplots(specs=[[{"secondary_y": True}]])

    fig.add_trace(
        go.Scatter(x=df_sim["date"], y=df_sim["inventory_level"], name="Inventario", mode="lines+markers"),
        secondary_y=False,
    )
    fig.add_trace(
        go.Scatter(
            x=df_sim["date"],
            y=df_sim["reorder_point_s"],
            name="Punto s",
            mode="lines",
            line={"dash": "dot"},
        ),
        secondary_y=False,
    )
    fig.add_trace(
        go.Bar(x=df_sim["date"], y=df_sim["demand_real"], name="Demanda mensual", opacity=0.35),
        secondary_y=True,
    )

    pedidos = df_sim[df_sim["order_placed"] > 0]
    fig.add_trace(
        go.Scatter(
            x=pedidos["date"],
            y=pedidos["order_placed"],
            name="Pedido generado",
            mode="markers",
            marker={"size": 10, "symbol": "triangle-up"},
        ),
        secondary_y=True,
    )

    fig.update_layout(title="Simulación mensual de inventario", hovermode="x unified")
    fig.update_yaxes(title_text="Inventario", secondary_y=False)
    fig.update_yaxes(title_text="Demanda / Pedidos", secondary_y=True)
    return fig

def grafico_tradeoff(df_opt: pd.DataFrame) -> go.Figure:
    mejor = df_opt.loc[df_opt["total_cost"].idxmin()]

    fig = go.Figure()
    fig.add_trace(go.Scatter(x=df_opt["ss_months"], y=df_opt["total_cost"], mode="lines+markers", name="Costo total"))
    fig.add_trace(go.Scatter(x=df_opt["ss_months"], y=df_opt["holding_cost"], mode="lines", name="Costo mantener"))
    fig.add_trace(go.Scatter(x=df_opt["ss_months"], y=df_opt["stockout_cost"], mode="lines", name="Costo quiebre"))
    fig.add_vline(
        x=int(mejor["ss_months"]),
        line_dash="dash",
        annotation_text=f"Óptimo: {int(mejor['ss_months'])} meses",
    )
    fig.update_layout(
        title="Trade-off de costos",
        xaxis_title="Meses de stock de seguridad",
        yaxis_title="Costo",
        hovermode="x unified",
    )
    return fig

def formatear_comparacion(df_comparacion: pd.DataFrame) -> pd.DataFrame:
    df = df_comparacion.copy()
    df["wMAPE"] = df["wMAPE"].map(lambda x: f"{x:.2%}")
    df["Bias"] = df["Bias"].map(lambda x: f"{x:.2%}")
    df["MAE"] = df["MAE"].map(lambda x: f"{x:,.2f}")
    df["Resultado"] = np.where(df["Es mejor"], "✅ Mejor", "")
    return df[["Producto", "Método", "wMAPE", "Bias", "MAE", "Resultado"]]
